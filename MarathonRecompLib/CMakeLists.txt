project("MarathonRecompLib")

add_compile_options(
    -fno-strict-aliasing
)

if (WIN32)
    add_compile_options(/fp:strict)
else()
    add_compile_options(-ffp-model=strict)
endif()

if (MARATHON_RECOMP_USE_PREBUILT_HOST_TOOLS)
    set(MARATHON_RECOMP_XENON_RECOMP_COMMAND "${MARATHON_RECOMP_HOST_XENON_RECOMP}")
    set(MARATHON_RECOMP_XENON_RECOMP_TOOL_DEPENDS "${MARATHON_RECOMP_HOST_XENON_RECOMP}")
    set(MARATHON_RECOMP_U8EXTRACT_COMMAND "${MARATHON_RECOMP_HOST_U8EXTRACT}")
    set(MARATHON_RECOMP_U8EXTRACT_TOOL_DEPENDS "${MARATHON_RECOMP_HOST_U8EXTRACT}")
    set(MARATHON_RECOMP_XENOS_RECOMP_COMMAND "${MARATHON_RECOMP_HOST_XENOS_RECOMP}")
    set(MARATHON_RECOMP_XENOS_RECOMP_TOOL_DEPENDS "${MARATHON_RECOMP_HOST_XENOS_RECOMP}")
else()
    # These paths are baked into the host tool binaries as compile-time definitions
    # (they read this same source tree), so they only need to be set when the tools
    # are actually being built in this pass, not when reusing prebuilt host binaries.
    target_compile_definitions(XenonRecomp PRIVATE
        XENON_RECOMP_CONFIG_FILE_PATH=\"${CMAKE_CURRENT_SOURCE_DIR}/config/Marathon.toml\"
        XENON_RECOMP_HEADER_FILE_PATH=\"${MARATHON_RECOMP_TOOLS_ROOT}/XenonRecomp/XenonUtils/ppc_context.h\")

    set(MARATHON_RECOMP_XENON_RECOMP_COMMAND "$<TARGET_FILE:XenonRecomp>")
    set(MARATHON_RECOMP_XENON_RECOMP_TOOL_DEPENDS XenonRecomp)
    set(MARATHON_RECOMP_U8EXTRACT_COMMAND "$<TARGET_FILE:u8extract>")
    set(MARATHON_RECOMP_U8EXTRACT_TOOL_DEPENDS u8extract)
    set(MARATHON_RECOMP_XENOS_RECOMP_COMMAND "$<TARGET_FILE:XenosRecomp>")
    set(MARATHON_RECOMP_XENOS_RECOMP_TOOL_DEPENDS XenosRecomp)
endif()

set(MARATHON_RECOMP_PPC_RECOMPILED_SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/ppc/ppc_config.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/ppc/ppc_context.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/ppc/ppc_func_mapping.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/ppc/ppc_recomp_shared.h"
)

foreach(i RANGE 0 145)
    list(APPEND MARATHON_RECOMP_PPC_RECOMPILED_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/ppc/ppc_recomp.${i}.cpp")
endforeach()

add_custom_command(
    OUTPUT
        ${MARATHON_RECOMP_PPC_RECOMPILED_SOURCES}
    COMMAND
        # The explicit arguments matter for prebuilt host tools compiled without the
        # XENON_RECOMP_CONFIG_FILE_PATH definition: such a binary invoked bare prints its
        # usage text and exits 0, so the rule "succeeds" without producing any outputs.
        # Binaries that do have the baked-in paths ignore these arguments entirely.
        ${MARATHON_RECOMP_XENON_RECOMP_COMMAND}
            "${CMAKE_CURRENT_SOURCE_DIR}/config/Marathon.toml"
            "${MARATHON_RECOMP_TOOLS_ROOT}/XenonRecomp/XenonUtils/ppc_context.h"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/private/default.xex"
        "${CMAKE_CURRENT_SOURCE_DIR}/config/Marathon.toml"
        ${MARATHON_RECOMP_XENON_RECOMP_TOOL_DEPENDS}
    USES_TERMINAL
)

add_custom_command(
    OUTPUT
        "${CMAKE_CURRENT_SOURCE_DIR}/private/shader"
    COMMAND
        ${MARATHON_RECOMP_U8EXTRACT_COMMAND} "${CMAKE_CURRENT_SOURCE_DIR}/private/shader.arc" "${CMAKE_CURRENT_SOURCE_DIR}/private/shader"
    COMMAND
        ${MARATHON_RECOMP_U8EXTRACT_COMMAND} "${CMAKE_CURRENT_SOURCE_DIR}/private/shader_lt.arc" "${CMAKE_CURRENT_SOURCE_DIR}/private/shader"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/private/shader.arc"
        "${CMAKE_CURRENT_SOURCE_DIR}/private/shader_lt.arc"
        ${MARATHON_RECOMP_U8EXTRACT_TOOL_DEPENDS}
)

set(XENOS_RECOMP_ROOT "${MARATHON_RECOMP_TOOLS_ROOT}/XenosRecomp/XenosRecomp")
# The generated copy of the submodule's header, not the submodule file itself: it is the
# one the port's own shaders are compiled against, and on Android it carries the four
# descriptor set binding layout the driver needs. See the top-level CMakeLists.txt.
set(XENOS_RECOMP_INCLUDE "${MARATHON_RECOMP_SHADER_COMMON_HEADER}")

if (NOT MARATHON_RECOMP_USE_PREBUILT_HOST_TOOLS)
    target_compile_definitions(XenosRecomp PRIVATE
        XENOS_RECOMP_INPUT=\"${CMAKE_CURRENT_SOURCE_DIR}/private/shader\"
        XENOS_RECOMP_OUTPUT=\"${CMAKE_CURRENT_SOURCE_DIR}/shader/shader_cache.cpp\"
        XENOS_RECOMP_INCLUDE_INPUT=\"${XENOS_RECOMP_INCLUDE}\"
        MARATHON_RECOMP
    )
endif()

file(GLOB XENOS_RECOMP_SOURCES 
    "${XENOS_RECOMP_ROOT}/*.h"
    "${XENOS_RECOMP_ROOT}/*.cpp"
)

add_custom_command(
    OUTPUT
        "${CMAKE_CURRENT_SOURCE_DIR}/shader/shader_cache.cpp"
    COMMAND
        # Explicit arguments for prebuilt host tools compiled without the
        # XENOS_RECOMP_INPUT/OUTPUT/INCLUDE_INPUT definitions: such a binary
        # invoked bare prints its usage text and exits 0, so the rule
        # "succeeds" without producing any outputs. Binaries that do have the
        # baked-in paths ignore these arguments entirely.
        ${MARATHON_RECOMP_XENOS_RECOMP_COMMAND}
            "${CMAKE_CURRENT_SOURCE_DIR}/private/shader"
            "${CMAKE_CURRENT_SOURCE_DIR}/shader/shader_cache.cpp"
            "${XENOS_RECOMP_INCLUDE}"
    DEPENDS
        "${CMAKE_CURRENT_SOURCE_DIR}/private/shader"
        ${XENOS_RECOMP_SOURCES}
        ${XENOS_RECOMP_INCLUDE}
        ${MARATHON_RECOMP_XENOS_RECOMP_TOOL_DEPENDS}
    USES_TERMINAL
)

add_library(MarathonRecompLib
    ${MARATHON_RECOMP_PPC_RECOMPILED_SOURCES}
    "shader/shader_cache.h"
    "shader/shader_cache.cpp"
)

target_include_directories(MarathonRecompLib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_include_directories(MarathonRecompLib PRIVATE "${MARATHON_RECOMP_TOOLS_ROOT}/XenonRecomp/thirdparty/simde")
target_precompile_headers(MarathonRecompLib PUBLIC "ppc/ppc_recomp_shared.h")

# Pulls ppc/ppc_detail.h (tracked, unlike the generated rest of ppc/) into the
# generated ppc_config.h: hardens PPC_CALL_INDIRECT_FUNC against out-of-range
# and unmapped targets (Android crash: indirect call through guest null).
# PUBLIC so every TU that includes the ppc headers sees the same macro
# definition as the precompiled header.
target_compile_definitions(MarathonRecompLib PUBLIC PPC_INCLUDE_DETAIL)
