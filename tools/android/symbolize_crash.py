#!/usr/bin/env python3
"""Resolve crash-report module offsets (e.g. "libmain.so+0x34661a8") to function names.

The Android crash reporter writes frames as "libmain.so+0x<offset>" because that is all
dladdr() can say once symbols are not exported. The offsets are file-relative virtual
addresses, so they can be resolved against the library's own .symtab - which the debug APK
keeps (see packagingOptions.jniLibs.keepDebugSymbols in android-apk/app/build.gradle).

No tools beyond Python are needed: the ELF symbol table is parsed directly, and libmain.so
can be pulled straight out of the APK, so a tester can run this anywhere:

    python3 tools/android/symbolize_crash.py --apk app-debug.apk --log log.txt
    python3 tools/android/symbolize_crash.py --so libmain.so --offsets 0x34661a8 0xeff1c0

With --log the script picks every "module.so+0x..." token out of the text (tombstones,
log.txt, pasted chat messages all work) and resolves the ones it has a module for. Useful
exit code: 0 if at least one offset resolved, 1 otherwise.
"""

import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

STT_NOTYPE = 0
STT_FUNC = 2
SHT_SYMTAB = 2

MODULE_OFFSET_RE = re.compile(r"([A-Za-z0-9._+-]+\.so)\+(0x)?([0-9a-fA-F]+)")


class Symbol:
    __slots__ = ("value", "size", "name")

    def __init__(self, value, size, name):
        self.value = value
        self.size = size
        self.name = name


def parse_elf64_symbols(path):
    """Return (sized, unsized) symbol lists sorted by address.

    sized: symbols with st_size > 0 - these are trusted to name an address inside them.
    unsized: function-ish symbols without a size - used only when nothing contains the
    address, since a nearby label is still a better answer than none.
    """
    with open(path, "rb") as handle:
        data = handle.read()

    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError("%s is not an ELF file" % path)
    if data[4] != 2:
        raise ValueError("%s is not a 64-bit ELF file" % path)
    if data[5] != 1:
        raise ValueError("%s is not little-endian" % path)

    e_shoff, = struct.unpack_from("<Q", data, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", data, 0x3A)
    if e_shoff == 0 or e_shnum == 0:
        return [], []

    def section(index):
        return struct.unpack_from("<IIQQQQIIQQ", data, e_shoff + index * e_shentsize)

    sized, unsized = [], []
    for index in range(e_shnum):
        sh_name, sh_type, _flags, _addr, sh_offset, sh_size, sh_link, _info, _align, sh_entsize = section(index)
        if sh_type != SHT_SYMTAB or sh_entsize != 24 or sh_size == 0:
            continue
        if sh_link >= e_shnum:
            continue

        _n, _t, _f, _a, str_offset, str_size = section(sh_link)[:6]
        strings = data[str_offset:str_offset + str_size]

        def string_at(offset):
            end = strings.find(b"\x00", offset)
            if end < 0:
                end = len(strings)
            return strings[offset:end].decode("utf-8", "replace")

        for entry in range(sh_offset, sh_offset + sh_size, 24):
            st_name, st_info, _other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", data, entry)
            if st_value == 0 or st_name == 0 or st_shndx == 0:
                continue
            kind = st_info & 0xF
            if kind not in (STT_FUNC, STT_NOTYPE):
                continue
            name = string_at(st_name)
            if not name:
                continue
            (sized if st_size else unsized).append(Symbol(st_value, st_size, name))

    sized.sort(key=lambda symbol: symbol.value)
    unsized.sort(key=lambda symbol: symbol.value)
    return sized, unsized


def resolve(offset, sized, unsized):
    """Name the function containing offset, or the closest function below it."""
    containing = None
    for symbol in sized:
        if symbol.value > offset:
            break
        if offset < symbol.value + symbol.size:
            containing = symbol
    if containing is not None:
        delta = offset - containing.value
        return containing.name + ("+0x%x" % delta if delta else "")

    # Each list is sorted, but they are not sorted against each other, so scan both.
    below = None
    for symbols in (sized, unsized):
        for symbol in symbols:
            if symbol.value > offset:
                break
            if below is None or symbol.value > below.value:
                below = symbol
    # A symbol far below the address is not a useful answer, it is a different section
    # (the .eh_frame pseudo-symbols sit at high addresses and would swallow anything).
    if below is None or offset - below.value > 0x1000:
        return None
    return "%s+0x%x (nearest symbol below; not inside any sized function)" % (below.name, offset - below.value)


def demangle(names):
    """Demangle with c++filt when it happens to be installed; keep raw names otherwise."""
    unique = [name for name in dict.fromkeys(names) if name.startswith("_Z")]
    if not unique:
        return {}
    try:
        process = subprocess.run(
            ["c++filt", "-n"], input="\n".join(unique), capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if process.returncode != 0:
        return {}
    demangled = process.stdout.split("\n")
    return dict(zip(unique, demangled)) if len(demangled) >= len(unique) else {}


def extract_from_apk(apk_path, wanted, dest_dir):
    """Extract the given .so (by basename) from the APK's arm64 lib dir."""
    if not os.path.isfile(apk_path):
        raise SystemExit("error: %s does not exist" % apk_path)
    with zipfile.ZipFile(apk_path) as archive:
        candidates = [name for name in archive.namelist() if os.path.basename(name) == wanted]
        if not candidates:
            available = sorted({os.path.basename(name) for name in archive.namelist() if name.endswith(".so")})
            raise SystemExit("error: %s is not in %s (present: %s)" % (wanted, apk_path, ", ".join(available) or "none"))
        member = sorted(candidates, key=len)[0]
        target = os.path.join(dest_dir, wanted)
        with archive.open(member) as source, open(target, "wb") as output:
            output.write(source.read())
        print("extracted %s (%.1f MB) from %s" % (member, os.path.getsize(target) / 1e6, os.path.basename(apk_path)))
        return target


def parse_offsets(text):
    """Return {module: [offset, ...]} for every module+offset token in text."""
    offsets = {}
    for module, _prefix, value in MODULE_OFFSET_RE.findall(text):
        offsets.setdefault(module, []).append(int(value, 16))
    return offsets


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--apk", help="debug APK to pull the native libraries out of")
    source.add_argument("--so", help="library file (e.g. libmain.so)")
    parser.add_argument("--log", help="log.txt / tombstone / pasted crash text to scan")
    parser.add_argument("--offsets", nargs="*", default=[], help="explicit offsets, e.g. 0xeff1c0")
    parser.add_argument("--module", default=None, help="module name for --offsets (default: the library's basename)")
    args = parser.parse_args()

    temporary = None
    if args.apk:
        temporary = tempfile.mkdtemp(prefix="symbolize_crash_")
        library = extract_from_apk(args.apk, "libmain.so", temporary)
        module_name = "libmain.so"
    else:
        library = args.so
        module_name = args.module or os.path.basename(library)

    requested = {}
    if args.log:
        with open(args.log, "r", errors="replace") as handle:
            requested.update(parse_offsets(handle.read()))
        if not requested:
            print("no module+offset tokens found in %s" % args.log)
    for value in args.offsets:
        requested.setdefault(args.module or module_name, []).append(int(value, 16))

    if not requested:
        parser.error("nothing to resolve: pass --log and/or --offsets")

    sized, unsized = parse_elf64_symbols(library)
    print("%s: %d sized + %d unsized function symbols" % (library, len(sized), len(unsized)))
    if not sized and not unsized:
        print("")
        print("This library has no .symtab, so offsets cannot be resolved from it.")
        print("It was stripped on the way into the APK; use the unstripped build output")
        print("(out/build/android-arm64/MarathonRecomp/libmain.so) or a build with")
        print("packagingOptions.jniLibs.keepDebugSymbols set for libmain.so.")
        return 1

    resolved_names, report, failures = [], [], 0
    for module in sorted(requested):
        for offset in sorted(set(requested[module])):
            if module != module_name:
                report.append((module, offset, None))
                failures += 1
                continue
            name = resolve(offset, sized, unsized)
            report.append((module, offset, name))
            if name is None:
                failures += 1
            else:
                resolved_names.append(name.split("+")[0])

    demangled = demangle(resolved_names)

    def readable(name):
        base, separator, suffix = name.partition("+")
        return (demangled.get(base, base) + separator + suffix) if separator else demangled.get(base, base)

    print("")
    for module, offset, name in report:
        if name is None and module == module_name:
            print("  %s+0x%x -> (no symbol at or below this offset)" % (module, offset))
        elif name is None:
            print("  %s+0x%x -> (module not supplied; pass --so/--apk for it)" % (module, offset))
        else:
            print("  %s+0x%x -> %s" % (module, offset, readable(name)))

    if not demangled and any(name.startswith("_Z") for name in resolved_names):
        print("")
        print("(names are mangled - install binutils/c++filt or paste them into a demangler)")

    print("")
    print("resolved %d of %d offsets" % (len(report) - failures, len(report)))
    return 0 if failures < len(report) else 1


if __name__ == "__main__":
    sys.exit(main())
