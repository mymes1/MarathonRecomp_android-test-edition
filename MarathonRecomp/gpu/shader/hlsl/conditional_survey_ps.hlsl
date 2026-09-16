// Resolved through the include directory compile_shader() passes to DXC: the same
// generated shader_common.h the game's recompiled shaders are built with (the Android
// build moves one declaration to keep the pipeline layout at four descriptor sets).
#include "shader_common.h"

#ifndef __spirv__

cbuffer SharedConstants : register(b2, space4)
{
	DEFINE_SHARED_CONSTANTS();
};

#endif

[earlydepthstencil]
float4 shaderMain() : SV_Target
{
    atomicFetchAddUint(g_ConditionalSurveyBuffer, g_conditionalSurveyIndex, 1);
    return float4(0.0, 0.0, 0.0, 0.0);
}
