#!/usr/bin/env bash
# Builds the host code-generation tools (XenonRecomp, XenosRecomp, file_to_c,
# u8extract) for the machine you are building on. These are needed to cross-compile
# the game to Android, because the recompiled code is generated at build time from
# the game's default.xex / shader archives by tools that must run on the host.
set -euo pipefail

repo="$(cd "$(dirname "$0")" && pwd)"
preset="${1:-linux-host-tools}"

if [ -z "${VCPKG_ROOT:-}" ]; then
    export VCPKG_ROOT="$repo/thirdparty/vcpkg"
fi

# The four-descriptor-set layout is baked into these tools (XenosRecomp reads the
# shader_common.h path it was configured with and ignores the one passed at runtime), so they
# have to be built the same way the Android build lays its pipeline layouts out. Mali caps
# maxBoundDescriptorSets at 4; build_android.sh's build fails the configure with an explanatory
# message if the tools and the build disagree.
cmake --preset "$preset" -DMARATHON_RECOMP_FOUR_DESCRIPTOR_SETS=ON
cmake --build "out/build/$preset" --target XenonRecomp XenosRecomp file_to_c u8extract

echo
echo "Host tools are ready in out/build/$preset:"
echo "  XenonRecomp : out/build/$preset/tools/XenonRecomp/XenonRecomp"
echo "  XenosRecomp : out/build/$preset/tools/XenosRecomp/XenosRecomp"
echo "  file_to_c   : out/build/$preset/tools/file_to_c/file_to_c"
echo "  u8extract   : out/build/$preset/tools/u8extract/u8extract"
