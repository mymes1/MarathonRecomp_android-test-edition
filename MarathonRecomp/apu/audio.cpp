#include <stdafx.h>

#include <bit>

#include "audio.h"
#include <kernel/memory.h>
#include <os/logger.h>

#define AUDIO_DRIVER_KEY (uint32_t)('DAUD')

// Use to dump raw audio captures to the game folder.
//#define AUDIO_DUMP_SAMPLES_PATH "audio.pcm"

#ifdef AUDIO_DUMP_SAMPLES_PATH
std::ofstream g_audioDumpStream;
#endif

uint32_t XAudioRegisterRenderDriverClient(be<uint32_t>* callback, be<uint32_t>* driver)
{
#ifdef AUDIO_DUMP_SAMPLES_PATH
    g_audioDumpStream.open(AUDIO_DUMP_SAMPLES_PATH, std::ios::binary);
#endif

    // The game passes a guest function address; it is not a recompiled function when the
    // object was half-built or the recompiler skipped it. Registering null used to make the
    // audio thread jump to null, so report it and let the driver's callback guard skip.
    PPCFunc* pCallback = g_memory.FindFunctionChecked(uint32_t(*callback));

    if (pCallback == nullptr)
    {
        LOGF_ERROR("Audio: render driver callback {:08X} is not a recompiled function; audio will stay silent.",
            uint32_t(*callback));
    }

    *driver = AUDIO_DRIVER_KEY;
    XAudioRegisterClient(pCallback, callback[1]);
    return 0;
}

uint32_t XAudioUnregisterRenderDriverClient(uint32_t driver)
{
    return 0;
}

uint32_t XAudioSubmitRenderDriverFrame(uint32_t driver, void* samples)
{
#ifdef AUDIO_DUMP_SAMPLES_PATH
    static uint32_t xaudioSamplesBuffer[XAUDIO_NUM_SAMPLES * XAUDIO_NUM_CHANNELS];
    for (size_t i = 0; i < XAUDIO_NUM_SAMPLES; i++)
    {
        for (size_t j = 0; j < XAUDIO_NUM_CHANNELS; j++)
        {
            xaudioSamplesBuffer[i * XAUDIO_NUM_CHANNELS + j] = ByteSwap(((uint32_t *)samples)[j * XAUDIO_NUM_SAMPLES + i]);
        }
    }

    g_audioDumpStream.write((const char *)(xaudioSamplesBuffer), sizeof(xaudioSamplesBuffer));
#endif

    XAudioSubmitFrame(samples);
    return 0;
}
