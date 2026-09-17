cmake_minimum_required (VERSION 3.20)

option(MARATHON_RECOMP_ANDROID "Build for Android. Does not use vcpkg; expects prebuilt host tool paths via MARATHON_RECOMP_HOST_*." OFF)

if(NOT MARATHON_RECOMP_ANDROID AND NOT DEFINED ENV{VCPKG_ROOT})
    message(FATAL_ERROR "VCPKG_ROOT is not defined!")
endif()

set(MARATHON_RECOMP_THIRDPARTY_ROOT ${CMAKE_SOURCE_DIR}/thirdparty)
set(MARATHON_RECOMP_TOOLS_ROOT ${CMAKE_SOURCE_DIR}/tools)
set(CMAKE_CXX_STANDARD 20)
set(BUILD_SHARED_LIBS OFF)

option(MARATHON_RECOMP_HOST_TOOLS_ONLY "Only build the host code-generation tools (XenonRecomp, XenosRecomp, file_to_c, u8extract), skipping the game executable and its platform-specific dependencies. Used to produce host binaries for cross-compiling to another target platform." OFF)

# When cross-compiling (e.g. to Android), these point at prebuilt host executables
# produced by a MARATHON_RECOMP_HOST_TOOLS_ONLY pass, since the in-tree tool targets
# would otherwise be built for the (unrunnable, on the host) target architecture.
set(MARATHON_RECOMP_HOST_XENON_RECOMP "" CACHE FILEPATH "Path to a prebuilt host XenonRecomp executable")
set(MARATHON_RECOMP_HOST_XENOS_RECOMP "" CACHE FILEPATH "Path to a prebuilt host XenosRecomp executable")
set(MARATHON_RECOMP_HOST_FILE_TO_C "" CACHE FILEPATH "Path to a prebuilt host file_to_c executable")
set(MARATHON_RECOMP_HOST_U8EXTRACT "" CACHE FILEPATH "Path to a prebuilt host u8extract executable")

# Enable Hot Reload for MSVC compilers if supported.
if (POLICY CMP0141)
  cmake_policy(SET CMP0141 NEW)
  set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<IF:$<AND:$<C_COMPILER_ID:MSVC>,$<CXX_COMPILER_ID:MSVC>>,$<$<CONFIG:Debug,RelWithDebInfo>:EditAndContinue>,$<$<CONFIG:Debug,RelWithDebInfo>:ProgramDatabase>>")
endif()

set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

project("MarathonRecomp-ALL")

if (APPLE)
    enable_language(OBJC OBJCXX)
endif()

if (CMAKE_OSX_ARCHITECTURES)
    set(MARATHON_RECOMP_ARCHITECTURE ${CMAKE_OSX_ARCHITECTURES})
elseif(CMAKE_SYSTEM_PROCESSOR)
    set(MARATHON_RECOMP_ARCHITECTURE ${CMAKE_SYSTEM_PROCESSOR})
else()
    set(MARATHON_RECOMP_ARCHITECTURE ${CMAKE_HOST_SYSTEM_PROCESSOR})
endif()
string(TOLOWER "${MARATHON_RECOMP_ARCHITECTURE}" MARATHON_RECOMP_ARCHITECTURE)
message(STATUS "Detected architecture: ${MARATHON_RECOMP_ARCHITECTURE}")

if (MARATHON_RECOMP_ARCHITECTURE STREQUAL "x86_64" OR MARATHON_RECOMP_ARCHITECTURE STREQUAL "amd64")
    # Target Sandy Bridge for all projects
    add_compile_options(
        -march=sandybridge
    )
endif()

if (CMAKE_BUILD_TYPE STREQUAL "Debug")
    # Normally only defined by Visual Studio, added for consistency
    add_compile_definitions(_DEBUG)
endif()

if (MARATHON_RECOMP_HOST_XENON_RECOMP AND MARATHON_RECOMP_HOST_XENOS_RECOMP AND MARATHON_RECOMP_HOST_FILE_TO_C AND MARATHON_RECOMP_HOST_U8EXTRACT)
    set(MARATHON_RECOMP_USE_PREBUILT_HOST_TOOLS ON)
else()
    set(MARATHON_RECOMP_USE_PREBUILT_HOST_TOOLS OFF)
endif()

if (MARATHON_RECOMP_ANDROID)
    # The HLSL -> DXIL/SPIR-V header step (compile_shader in MarathonRecomp/CMakeLists.txt)
    # must run on the HOST. The dxc-bin CMakeLists inside the tools/XenosRecomp submodule
    # resolves against the TARGET architecture, which breaks cross-compiling, so define the
    # imported Microsoft::DirectXShaderCompiler target and DIRECTX_DXC_TOOL here instead;
    # XenosRecomp's thirdparty CMake then skips its own add_subdirectory(dxc-bin).
    if (CMAKE_HOST_WIN32)
        set(DXC_HOST_PLATFORM "win32")
    elseif (CMAKE_HOST_APPLE)
        set(DXC_HOST_PLATFORM "apple")
    else()
        set(DXC_HOST_PLATFORM "linux")
    endif()

    if (CMAKE_HOST_SYSTEM_PROCESSOR MATCHES "(x86)|(X86)|(amd64)|(AMD64)")
        set(DXC_HOST_ARCH "x64")
    else()
        set(DXC_HOST_ARCH "arm64")
    endif()

    set(DXC_BIN_ROOT "${MARATHON_RECOMP_TOOLS_ROOT}/XenosRecomp/thirdparty/dxc-bin")

    if (DXC_HOST_PLATFORM STREQUAL "win32")
        set(DIRECTX_DXC_TOOL "${DXC_BIN_ROOT}/bin/${DXC_HOST_ARCH}/dxc.exe" CACHE INTERNAL "")
        set(DXC_DXCOMPILER_LIB "${DXC_BIN_ROOT}/lib/${DXC_HOST_ARCH}/dxcompiler.lib")
    elseif (DXC_HOST_PLATFORM STREQUAL "apple")
        set(DIRECTX_DXC_TOOL "DYLD_LIBRARY_PATH=${DXC_BIN_ROOT}/lib/${DXC_HOST_ARCH}" "${DXC_BIN_ROOT}/bin/${DXC_HOST_ARCH}/dxc-macos" CACHE INTERNAL "")
        set(DXC_DXCOMPILER_LIB "${DXC_BIN_ROOT}/lib/${DXC_HOST_ARCH}/libdxcompiler.dylib")
    else()
        set(DIRECTX_DXC_TOOL "LD_LIBRARY_PATH=${DXC_BIN_ROOT}/lib/${DXC_HOST_ARCH}" "${DXC_BIN_ROOT}/bin/${DXC_HOST_ARCH}/dxc-linux" CACHE INTERNAL "")
        set(DXC_DXCOMPILER_LIB "${DXC_BIN_ROOT}/lib/${DXC_HOST_ARCH}/libdxcompiler.so")
    endif()

    add_library(Microsoft::DirectXShaderCompiler SHARED IMPORTED GLOBAL)
    set_target_properties(Microsoft::DirectXShaderCompiler PROPERTIES
        INTERFACE_INCLUDE_DIRECTORIES "${DXC_BIN_ROOT}/inc"
        IMPORTED_LOCATION "${DXC_DXCOMPILER_LIB}"
    )
endif()

# The shader binding layout has to be identical in three places: the recompiled game
# shaders (XenosRecomp inlines shader_common.h into every shader it generates), the port's
# own HLSL shaders, and the packet of descriptor set layouts built in gpu/video.cpp.
# XenosRecomp takes the header path as an argument, so the build feeds both consumers the
# same generated copy instead of the submodule path. Android additionally patches one
# declaration in it; see cmake/generate_shader_common.cmake for why (Mali's
# maxBoundDescriptorSets is 4).
#
# Android defaults to the four-set layout because Mali and other mobile drivers cap
# maxBoundDescriptorSets at 4. A host-tools pass defaults the same way because the tools it
# produces are consumed by such a build: a prebuilt XenosRecomp reads the header baked into it
# at its own configure time, so tools built for five sets are of no use to an Android build.
# Both defaults are only defaults - the value can be passed explicitly, and the check below
# refuses to combine a build with host tools that were configured for the other layout.
if (MARATHON_RECOMP_ANDROID OR MARATHON_RECOMP_HOST_TOOLS_ONLY)
    set(MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS_DEFAULT ON)
else()
    set(MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS_DEFAULT OFF)
endif()

option(MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS
    "Compile shaders and build pipeline layouts for four descriptor sets (required on Mali)"
    ${MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS_DEFAULT})

set(MARATHON_RECOMP_SHADER_COMMON_SOURCE "${MARATHON_RECOMP_TOOLS_ROOT}/XenosRecomp/XenosRecomp/shader_common.h")
set(MARATHON_RECOMP_SHADER_COMMON_DIR "${CMAKE_BINARY_DIR}/shader_common")
set(MARATHON_RECOMP_SHADER_COMMON_HEADER "${MARATHON_RECOMP_SHADER_COMMON_DIR}/shader_common.h")

add_custom_command(
    OUTPUT "${MARATHON_RECOMP_SHADER_COMMON_HEADER}"
    COMMAND ${CMAKE_COMMAND}
        -DSRC=${MARATHON_RECOMP_SHADER_COMMON_SOURCE}
        -DOUT=${MARATHON_RECOMP_SHADER_COMMON_HEADER}
        -DFOUR_DESCRIPTOR_SETS=${MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS}
        -P "${CMAKE_SOURCE_DIR}/cmake/generate_shader_common.cmake"
    DEPENDS
        "${MARATHON_RECOMP_SHADER_COMMON_SOURCE}"
        "${CMAKE_SOURCE_DIR}/cmake/generate_shader_common.cmake"
    COMMENT "Generating the shader_common.h the shader build and the shader recompiler use"
    VERBATIM
)

# Both consumers of the generated header (the shader compile rules in MarathonRecomp and the
# XenosRecomp invocation in MarathonRecompLib) live in subdirectories, and a custom command
# output that only subdirectories depend on is not given a build rule at all: ninja then fails
# with "shader_common/shader_common.h, needed by ..., missing and no known rule to make it".
# Depending on the output here as well is what makes CMake emit the rule; it does not change
# the dependency edges of the consumers, which stay on the file and so still rebuild the
# shaders whenever the header changes.
add_custom_target(MarathonRecompShaderCommonHeader DEPENDS "${MARATHON_RECOMP_SHADER_COMMON_HEADER}")

# A prebuilt XenosRecomp reads shader_common.h from the path baked into it at ITS configure time
# (main.cpp prefers XENOS_RECOMP_INCLUDE_INPUT over argv[3]) and silently ignores the path this
# build passes on the command line. Host tools configured for the other layout would therefore
# recompile the game's shaders against a descriptor set layout the renderer does not build, which
# shows up as mis-bound resources on the device rather than as a build error. The baked path is a
# string in the binary, so check the file it actually points at instead of trusting the caller.
if (MARATHON_RECOMP_USE_PREBUILT_HOST_TOOLS AND EXISTS "${MARATHON_RECOMP_HOST_XENOS_RECOMP}")
    file(STRINGS "${MARATHON_RECOMP_HOST_XENOS_RECOMP}" MARATHON_RECOMP_BAKED_SHADER_COMMON_PATHS REGEX "shader_common\\.h")

    # No baked path at all means the tool falls back to the include argument this build passes,
    # which is always the generated header this build expects.
    if (MARATHON_RECOMP_BAKED_SHADER_COMMON_PATHS)
        set(MARATHON_RECOMP_BAKED_SHADER_COMMON_FOUND FALSE)
        set(MARATHON_RECOMP_BAKED_SHADER_COMMON_PATCHED FALSE)
        foreach (bakedPath IN LISTS MARATHON_RECOMP_BAKED_SHADER_COMMON_PATHS)
            if (EXISTS "${bakedPath}")
                file(READ "${bakedPath}" bakedContents)
                # Keep in step with the declaration cmake/generate_shader_common.cmake rewrites.
                if (bakedContents MATCHES "g_ConditionalSurveyBuffer[^;]*register\\(u1, space3\\)")
                    set(MARATHON_RECOMP_BAKED_SHADER_COMMON_PATCHED TRUE)
                else()
                    set(MARATHON_RECOMP_BAKED_SHADER_COMMON_PATCHED FALSE)
                endif()
                set(MARATHON_RECOMP_BAKED_SHADER_COMMON_FOUND TRUE)
                # foreach() clears its loop variable when the loop ends, so keep the path.
                set(bakedShaderCommonPath "${bakedPath}")
                break()
            endif()
        endforeach()

        if (NOT MARATHON_RECOMP_BAKED_SHADER_COMMON_FOUND)
            message(FATAL_ERROR
                "The prebuilt XenosRecomp at '${MARATHON_RECOMP_HOST_XENOS_RECOMP}' reads its "
                "shader_common.h from a path that does not exist (looked for: "
                "${MARATHON_RECOMP_BAKED_SHADER_COMMON_PATHS}), so it would fail the moment it runs. "
                "Build the host tools in this checkout first (build_host_tools.sh, or the host tools "
                "step of the Android workflow): that both builds the tool and generates the header it "
                "reads. A tool built in a different checkout or moved here cannot find its header.")
        else()
            if (MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS)
                set(bakedLayoutExpected "four")
                set(hostToolsHint "-DMARATHON_RECOMP_FOUR_DESCRIPTOR_SETS=ON")
            else()
                set(bakedLayoutExpected "five")
                set(hostToolsHint "-DMARATHON_RECOMP_FOUR_DESCRIPTOR_SETS=OFF")
            endif()

            if (MARATHON_RECOMP_BAKED_SHADER_COMMON_PATCHED)
                set(bakedLayoutActual "four")
            else()
                set(bakedLayoutActual "five")
            endif()

            if (NOT bakedLayoutActual STREQUAL bakedLayoutExpected)
                message(FATAL_ERROR
                    "The prebuilt XenosRecomp at '${MARATHON_RECOMP_HOST_XENOS_RECOMP}' reads "
                    "'${bakedShaderCommonPath}', a shader_common.h that lays the occlusion survey buffer out for "
                    "${bakedLayoutActual} descriptor sets, while this build lays out ${bakedLayoutExpected}. "
                    "They have to agree, or the game's recompiled shaders bind their resources to sets the "
                    "renderer does not use. Rebuild the host tools with ${hostToolsHint} (the "
                    "MARATHON_RECOMP_HOST_TOOLS_ONLY pass), then configure this build again.")
            endif()
        endif()
    endif()
endif()

if (MARATHON_RECOMP_HOST_TOOLS_ONLY)
    add_subdirectory(${MARATHON_RECOMP_TOOLS_ROOT})

    # A host-tools pass exists to produce the tools for a game build elsewhere, and a prebuilt
    # XenosRecomp reads its shader_common.h from the path baked in here, so the file has to exist
    # in this build tree as well. Nothing else in this configure compiles a shader, so give the
    # generation rule an edge from the tool that depends on it (the CI builds these targets
    # explicitly rather than "all", so the default target is not enough).
    if (TARGET XenosRecomp)
        add_dependencies(XenosRecomp MarathonRecompShaderCommonHeader)
    endif()
else()
    add_subdirectory(${MARATHON_RECOMP_THIRDPARTY_ROOT})

    # tools/ also provides shared thirdparty libraries (fmt, zstd, xxHash) that
    # MarathonRecomp links against directly, so it's always added even when the
    # recompiler executables themselves are swapped out for prebuilt host binaries below.
    add_subdirectory(${MARATHON_RECOMP_TOOLS_ROOT})

    # Include sub-projects.
    add_subdirectory("MarathonRecompLib")
    add_subdirectory("MarathonRecomp")
endif()
