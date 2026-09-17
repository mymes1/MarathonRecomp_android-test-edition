# Generates the copy of XenosRecomp's shader_common.h that is fed to both the
# shader recompiler (as the include it inlines into every generated game shader)
# and the port's own HLSL shaders (through the include directory added by
# compile_shader() in MarathonRecomp/CMakeLists.txt).
#
# The Android build patches exactly one declaration: the occlusion-survey buffer.
# It normally lives in its own descriptor set (u0, space4), which puts the render
# pipeline layout at five descriptor sets. Mali (and other mobile drivers, e.g.
# PowerVR) report maxBoundDescriptorSets = 4, so a five-set layout cannot be
# created at all on those GPUs. Moving the buffer into the sampler set as a second
# binding brings the pipeline layout back to four sets, which every Vulkan device
# supports (the Vulkan minimum for maxBoundDescriptorSets is also four).
#
# D3D12 can represent this too (plume splits each set into a view table and a
# sampler table there, and the set index doubles as the register space), but only
# Android needs it: desktop drivers allow five sets, and leaving their layout
# alone keeps that path identical to what it was. So this is Android-only: every
# other platform gets a byte-for-byte copy and keeps the original five-set layout.
#
# Invoked as:
#   cmake -DSRC=<submodule header> -DOUT=<generated header> -DFOUR_DESCRIPTOR_SETS=<ON|OFF>
#         -P cmake/generate_shader_common.cmake

if (NOT DEFINED SRC OR NOT DEFINED OUT)
    message(FATAL_ERROR "generate_shader_common.cmake requires -DSRC= and -DOUT=")
endif()

if (NOT EXISTS "${SRC}")
    message(FATAL_ERROR
        "shader_common.h was not found at '${SRC}'. Initialize the submodules "
        "(git submodule update --init --recursive) before configuring.")
endif()

file(READ "${SRC}" content)

if (FOUR_DESCRIPTOR_SETS)
    # u0/space4 -> u1/space3: the sampler set (space3) already carries binding 0 for
    # the sampler heap, so the survey buffer takes binding 1 of the same set.
    set(needle "RWStructuredBuffer<uint>[ \t]*g_ConditionalSurveyBuffer[ \t]*:[ \t]*register[ \t]*\\([ \t]*u0[ \t]*,[ \t]*space4[ \t]*\\)[ \t]*;")
    set(replacement "RWStructuredBuffer<uint> g_ConditionalSurveyBuffer : register(u1, space3);")

    string(REGEX REPLACE "${needle}" "${replacement}" patched "${content}")

    if (patched STREQUAL content)
        message(FATAL_ERROR
            "Could not move g_ConditionalSurveyBuffer into the sampler set: the "
            "declaration was not found in '${SRC}'. The XenosRecomp submodule changed "
            "its shader binding layout, so cmake/generate_shader_common.cmake needs to "
            "be updated (a four-set layout is required on Mali GPUs, which cap "
            "maxBoundDescriptorSets at 4).")
    endif()

    set(content "${patched}")
endif()

# Only rewrite the file when the contents actually changed, so that a re-configure
# does not invalidate the generated shader cache and every shader object with it.
set(previous "")
if (EXISTS "${OUT}")
    file(READ "${OUT}" previous)
endif()

if (NOT previous STREQUAL content)
    get_filename_component(out_dir "${OUT}" DIRECTORY)
    file(MAKE_DIRECTORY "${out_dir}")
    file(WRITE "${OUT}" "${content}")
endif()
