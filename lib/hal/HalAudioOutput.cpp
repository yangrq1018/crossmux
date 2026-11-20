#include "HalAudioOutput.h"

#if CROSSPOINT_CAP_SOUND_FEEDBACK

#include <AudioManager.h>
#include <BoardConfig.h>
#include <Logging.h>

#if FREEINK_DEVICE_WAVESHARE_EPAPER_397
#include "Waveshare397Power.h"
#endif

namespace HalAudioOutput {
namespace {

constexpr unsigned long AUDIO_RAIL_SETTLE_MS = 10;

AudioManager audio;
bool initialized = false;

bool setBoardPower(const bool enabled) {
#if FREEINK_DEVICE_WAVESHARE_EPAPER_397
  return Waveshare397Power::setAudioPower(enabled);
#else
  (void)enabled;
  return true;
#endif
}

bool begin() {
  if (initialized) return true;
  if (!setBoardPower(true)) {
    LOG_ERR("SND", "Failed to enable board audio power");
    return false;
  }
#if FREEINK_DEVICE_WAVESHARE_EPAPER_397
  delay(AUDIO_RAIL_SETTLE_MS);
#endif
  if (!audio.begin()) {
    LOG_ERR("SND", "Failed to initialize audio output");
    setBoardPower(false);
    return false;
  }
  initialized = true;
  return true;
}

}  // namespace

bool playPcm(const ReadCallback read, const SeekCallback seek, const uint32_t sampleRate, const uint8_t channels,
             const uint8_t volume) {
  if (!read || !begin()) return false;
  audio.setVolume(volume);
  AudioManager::PcmSource source = {read, seek};
  if (audio.playPcm(source, sampleRate, channels)) return true;
  LOG_ERR("SND", "Failed to play feedback PCM");
  shutdown();
  return false;
}

bool restart(const uint8_t volume) {
  if (!initialized) return false;
  audio.setVolume(volume);
  return audio.requestRestart();
}

void setVolume(const uint8_t volume) {
  if (initialized) audio.setVolume(volume);
}

void shutdown() {
  if (!initialized) return;
  audio.powerDown();
  if (!setBoardPower(false)) LOG_ERR("SND", "Failed to disable board audio power");
  initialized = false;
}

}  // namespace HalAudioOutput

#endif

#if FREEINK_DEVICE_METALIO_EINK4

#include <Logging.h>
#include <MetalioAudio.h>

#include <algorithm>
#include <array>

namespace HalAudioOutput {
namespace {

namespace metalio = freeink::metalio;

constexpr i2s_chan_config_t DMA_CONFIG = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_SLAVE);
constexpr size_t FRAMES_PER_BUFFER = DMA_CONFIG.dma_frame_num;
constexpr size_t FRAMES_PER_NOTE = 4 * FRAMES_PER_BUFFER;
constexpr size_t FADE_FRAMES = metalio::AUDIO_RATE / 100;
constexpr uint8_t CHIME_VOLUME = 38;
constexpr uint32_t WRITE_TIMEOUT_MS = 150;
using StereoBuffer = std::array<int32_t, FRAMES_PER_BUFFER * 2>;

bool writeBuffer(const StereoBuffer& buffer) {
  size_t written = 0;
  const size_t bytes = sizeof(buffer);
  return i2s_channel_write(metalio::audioBus().tx, buffer.data(), bytes, &written, WRITE_TIMEOUT_MS) == ESP_OK &&
         written == bytes;
}

bool playChime() {
  // Queue silence first to check the module's I2S clocks before enabling the amplifier.
  StereoBuffer buffer{};
  if (!writeBuffer(buffer) || !metalio::setAmplifier(true)) return false;

  // Two descending notes at 800 and 640 Hz. Fade their edges to suppress clicks.
  for (const int period : {20, 25}) {
    for (size_t offset = 0; offset < FRAMES_PER_NOTE; offset += FRAMES_PER_BUFFER) {
      for (size_t i = 0; i < FRAMES_PER_BUFFER; ++i) {
        const size_t frame = offset + i;
        const int phase = static_cast<int>(frame % period);
        const int triangle = 4 * std::min(phase, period - phase) - period;
        const int fade = static_cast<int>(std::min({frame, FRAMES_PER_NOTE - 1 - frame, FADE_FRAMES}));
        const auto sample = static_cast<int16_t>(triangle * 24000 * fade / (period * static_cast<int>(FADE_FRAMES)));
        buffer[2 * i] = buffer[2 * i + 1] = metalio::outputSample(sample, CHIME_VOLUME);
      }
      if (!writeBuffer(buffer)) return false;
    }
  }

  // Writing a full ring of silence guarantees the last tone has left the DMA ring.
  buffer.fill(0);
  for (size_t i = 0; i < DMA_CONFIG.dma_desc_num; ++i) {
    if (!writeBuffer(buffer)) return false;
  }
  return true;
}

}  // namespace

void playSleepChime() {
  static const uint8_t owner = 0;
  if (!metalio::acquireAudio(&owner, false)) {
    LOG_ERR("SND", "Failed to initialize Metalio speaker");
    return;
  }
  if (!metalio::startAudio(&owner, false) || !playChime()) {
    LOG_ERR("SND", "Failed to play Metalio sleep chime");
  }
  if (!metalio::setAmplifier(false)) LOG_ERR("SND", "Failed to mute Metalio speaker");
  metalio::releaseAudio(&owner, false);
}

}  // namespace HalAudioOutput

#endif
