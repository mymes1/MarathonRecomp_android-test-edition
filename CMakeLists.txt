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
# shaders (XenosRecomp inlines shader_common.h into every generated shader), the port's
# own HLSL shaders, and the packet of descriptor set layouts built in gpu/video.cpp.
# XenosRecomp takes the header path as an argument (and the in-tree build bakes it in as
# XENOS_RECOMP_INCLUDE_INPUT), so the build feeds both consumers the same generated copy
# instead of the submodule path. Android additionally patches one declaration in it; see
# cmake/generate_shader_common.cmake for why (Mali's maxBoundDescriptorSets is 4).
if (MARATHON_RECOMP_ANDROID)
    set(MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS ON)
else()
    set(MARATHON_RECOMP_FOUR_DESCRIPTOR_SETS OFF)
endif()

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

if (MARATHON_RECOMP_HOST_TOOLS_ONLY)
    add_subdirectory(${MARATHON_RECOMP_TOOLS_ROOT})
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
