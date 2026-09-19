#pragma once

#ifndef _WIN32
#define MEM_COMMIT  0x00001000  
#define MEM_RESERVE 0x00002000  
#endif

struct PPCContext;

// Defined in kernel/memory.cpp, declared here as well as in
// MarathonRecompLib/ppc/ppc_detail.h (the recompiled code's copy, pulled in by the
// generated ppc_config.h): reports a guest function pointer that was never registered and
// skips the call instead of jumping to null or garbage.
extern "C" void PPCIndirectCallMissing(PPCContext& ctx, uint8_t* base, uint32_t target);

struct Memory
{
    uint8_t* base{};

    Memory();

    bool IsInMemoryRange(const void* host) const noexcept
    {
        return host >= base && host < (base + PPC_MEMORY_SIZE);
    }

    void* Translate(size_t offset) const noexcept
    {
        if (offset)
            assert(offset < PPC_MEMORY_SIZE);

        return base + offset;
    }

    uint32_t MapVirtual(const void* host) const noexcept
    {
        if (host)
            assert(IsInMemoryRange(host));

        return static_cast<uint32_t>(static_cast<const uint8_t*>(host) - base);
    }

    PPCFunc* FindFunction(uint32_t guest) const noexcept
    {
        return PPC_LOOKUP_FUNC(base, guest);
    }

    // FindFunction() for a value that came out of guest memory - a vtable slot, a callback
    // field - rather than from a guest code offset. Those can be null or arbitrary, and
    // PPC_LOOKUP_FUNC uses the value to index the function table, so anything outside the
    // image reads outside it and hands back whatever is there. A null return means "this
    // cannot be a registered recompiled function"; callers should report and skip it (see
    // GuestToHostFunction in kernel/function.h). Same range test as PPC_CALL_INDIRECT_FUNC
    // in MarathonRecompLib/ppc/ppc_detail.h, which guards the recompiled-code path.
    PPCFunc* FindFunctionChecked(uint32_t guest) const noexcept
    {
        if (uint64_t(guest) - PPC_CODE_BASE >= uint64_t(PPC_IMAGE_BASE + PPC_IMAGE_SIZE - PPC_CODE_BASE))
            return nullptr;

        return PPC_LOOKUP_FUNC(base, guest);
    }

    void InsertFunction(uint32_t guest, PPCFunc* host)
    {
        PPC_LOOKUP_FUNC(base, guest) = host;
    }
};

extern "C" void* MmGetHostAddress(uint32_t ptr);
extern Memory g_memory;
