#include "wasapi_loopback_audio.h"

#ifdef _WIN32
#include <windows.h>
#include <audioclient.h>
#include <mmdeviceapi.h>
#include <ksmedia.h>
#include <wrl/client.h>

#include <algorithm>
#include <cmath>
#include <cstring>
#include <utility>
#include <span>

using Microsoft::WRL::ComPtr;

LazyWasapiLoopbackAudio::~LazyWasapiLoopbackAudio() { Stop(); }

void LazyWasapiLoopbackAudio::SetEventCallback(
    std::function<void(const char*, const char*)> callback) {
  std::lock_guard<std::mutex> lock(mutex_);
  event_callback_ = std::move(callback);
}

void LazyWasapiLoopbackAudio::NotifyEvent(const char* type, const char* data) {
  std::function<void(const char*, const char*)> callback;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    callback = event_callback_;
  }
  if (callback) callback(type, data);
}

void LazyWasapiLoopbackAudio::AddRef() const { refs_.fetch_add(1, std::memory_order_relaxed); }
webrtc::RefCountReleaseStatus LazyWasapiLoopbackAudio::Release() const {
  const int left = refs_.fetch_sub(1, std::memory_order_acq_rel) - 1;
  if (left == 0) { delete this; return webrtc::RefCountReleaseStatus::kDroppedLastRef; }
  return webrtc::RefCountReleaseStatus::kOtherRefsRemained;
}
webrtc::MediaSourceInterface::SourceState LazyWasapiLoopbackAudio::state() const {
  return state_.load(std::memory_order_acquire);
}
void LazyWasapiLoopbackAudio::RegisterObserver(webrtc::ObserverInterface* o) {
  if (!o) return; std::lock_guard<std::mutex> l(mutex_);
  if (std::find(observers_.begin(), observers_.end(), o) == observers_.end()) observers_.push_back(o);
}
void LazyWasapiLoopbackAudio::UnregisterObserver(webrtc::ObserverInterface* o) {
  std::lock_guard<std::mutex> l(mutex_); observers_.erase(std::remove(observers_.begin(), observers_.end(), o), observers_.end());
}
void LazyWasapiLoopbackAudio::AddSink(webrtc::AudioTrackSinkInterface* s) {
  if (!s) return; std::lock_guard<std::mutex> l(mutex_);
  if (std::find(sinks_.begin(), sinks_.end(), s) == sinks_.end()) sinks_.push_back(s);
}
void LazyWasapiLoopbackAudio::RemoveSink(webrtc::AudioTrackSinkInterface* s) {
  std::lock_guard<std::mutex> l(mutex_); sinks_.erase(std::remove(sinks_.begin(), sinks_.end(), s), sinks_.end());
}
bool LazyWasapiLoopbackAudio::Start() {
  bool expected = false;
  if (!running_.compare_exchange_strong(expected, true)) return true;
  // A previous capture attempt may have ended asynchronously. Reap that
  // thread before assigning a new std::thread (assigning over a joinable
  // thread would terminate the process).
  if (thread_.joinable() && thread_.get_id() != std::this_thread::get_id()) {
    thread_.join();
  }
  state_.store(kLive, std::memory_order_release);
  thread_ = std::thread([this] { CaptureLoop(); });
  return true;
}
void LazyWasapiLoopbackAudio::Stop() {
  running_.store(false, std::memory_order_release);
  if (thread_.joinable() && thread_.get_id() != std::this_thread::get_id()) thread_.join();
  state_.store(kMuted, std::memory_order_release);
}
void LazyWasapiLoopbackAudio::Publish(const int16_t* pcm, size_t frames) {
  std::lock_guard<std::mutex> l(mutex_);
  for (auto* sink : sinks_) {
    if (sink) sink->OnData(pcm, 16, 48000, 2, frames, std::nullopt);
  }
}
void LazyWasapiLoopbackAudio::CaptureLoop() {
  const HRESULT com_hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  ComPtr<IMMDeviceEnumerator> enumerator;
  ComPtr<IMMDevice> device;
  ComPtr<IAudioClient> client;
  ComPtr<IAudioCaptureClient> capture;
  WAVEFORMATEX* mix = nullptr;
  HRESULT hr = CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL,
                                IID_PPV_ARGS(&enumerator));
  if (SUCCEEDED(hr)) hr = enumerator->GetDefaultAudioEndpoint(eRender, eConsole, &device);
  if (SUCCEEDED(hr)) hr = device->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, &client);
  if (SUCCEEDED(hr)) hr = client->GetMixFormat(&mix);
  if (SUCCEEDED(hr)) hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED,
      AUDCLNT_STREAMFLAGS_LOOPBACK, 1000000, 0, mix, nullptr);
  if (SUCCEEDED(hr)) hr = client->GetService(IID_PPV_ARGS(&capture));
  if (FAILED(hr)) {
    OutputDebugStringA("[LazyPC audio] WASAPI loopback initialization failed\n");
    NotifyEvent("audio_error", "wasapi_initialization_failed");
    running_.store(false); state_.store(kEnded);
    if (mix) CoTaskMemFree(mix); if (SUCCEEDED(com_hr)) CoUninitialize(); return;
  }
  hr = client->Start();
  if (FAILED(hr)) {
    OutputDebugStringA("[LazyPC audio] WASAPI loopback start failed\n");
    NotifyEvent("audio_error", "wasapi_client_start_failed");
    running_.store(false); state_.store(kEnded); CoTaskMemFree(mix); if (SUCCEEDED(com_hr)) CoUninitialize(); return;
  }
  // The Windows default render mix is commonly 48 kHz float stereo. This
  // bridge intentionally accepts only that format or 48 kHz 16-bit PCM rather
  // than silently mis-decoding an unsupported device format.
  const bool is_float = mix->wFormatTag == WAVE_FORMAT_IEEE_FLOAT ||
      (mix->wFormatTag == WAVE_FORMAT_EXTENSIBLE && mix->cbSize >= 22 &&
       reinterpret_cast<WAVEFORMATEXTENSIBLE*>(mix)->SubFormat == KSDATAFORMAT_SUBTYPE_IEEE_FLOAT);
  const bool is_pcm16 = (mix->wFormatTag == WAVE_FORMAT_PCM && mix->wBitsPerSample == 16) ||
      (mix->wFormatTag == WAVE_FORMAT_EXTENSIBLE && mix->cbSize >= 22 &&
       reinterpret_cast<WAVEFORMATEXTENSIBLE*>(mix)->SubFormat == KSDATAFORMAT_SUBTYPE_PCM && mix->wBitsPerSample == 16);
  if (mix->nSamplesPerSec != 48000 || (mix->nChannels != 1 && mix->nChannels != 2) ||
      (!is_float && !is_pcm16)) {
    OutputDebugStringA("[LazyPC audio] Unsupported WASAPI mix format; expected 48 kHz float/PCM16 mono/stereo\n");
    NotifyEvent("audio_error", "unsupported_wasapi_mix_format");
    client->Stop(); running_.store(false); state_.store(kEnded); CoTaskMemFree(mix); if (SUCCEEDED(com_hr)) CoUninitialize(); return;
  }
  OutputDebugStringA("[LazyPC audio] WASAPI loopback started\n");
  NotifyEvent("audio_capture", "started");
  while (running_.load(std::memory_order_acquire)) {
    UINT32 packet = 0;
    hr = capture->GetNextPacketSize(&packet);
    if (FAILED(hr)) break;
    if (!packet) { Sleep(5); continue; }
    while (packet && running_.load(std::memory_order_acquire)) {
      BYTE* data = nullptr; UINT32 frames = 0; DWORD flags = 0;
      hr = capture->GetBuffer(&data, &frames, &flags, nullptr, nullptr);
      if (FAILED(hr)) break;
      std::vector<int16_t> pcm(static_cast<size_t>(frames) * 2, 0);
      if (!(flags & AUDCLNT_BUFFERFLAGS_SILENT) && data) {
        const std::span<const std::byte> audio_bytes(
            reinterpret_cast<const std::byte*>(data),
            static_cast<size_t>(frames) * mix->nBlockAlign);
        for (UINT32 i = 0; i < frames; ++i) {
          for (int ch = 0; ch < 2; ++ch) {
            const UINT32 src_ch = mix->nChannels == 1 ? 0 : static_cast<UINT32>(ch);
            int16_t value = 0;
            const size_t sample_index =
                static_cast<size_t>(i) * mix->nChannels + src_ch;
            if (is_float) {
              float f = 0.0f;
              const auto sample_bytes = audio_bytes.subspan(
                  sample_index * sizeof(float), sizeof(float));
              std::memcpy(&f, sample_bytes.data(), sizeof(float));
              f = std::max(-1.0f, std::min(1.0f, f));
              value = static_cast<int16_t>(f * 32767.0f);
            } else {
              const auto sample_bytes = audio_bytes.subspan(
                  sample_index * sizeof(int16_t), sizeof(int16_t));
              std::memcpy(&value, sample_bytes.data(), sizeof(int16_t));
            }
            pcm[static_cast<size_t>(i) * 2 + ch] = value;
          }
        }
      }
      Publish(pcm.data(), frames);
      capture->ReleaseBuffer(frames);
      hr = capture->GetNextPacketSize(&packet);
      if (FAILED(hr)) break;
    }
  }
  client->Stop(); CoTaskMemFree(mix); running_.store(false); state_.store(kEnded);
  OutputDebugStringA("[LazyPC audio] WASAPI loopback stopped\n");
  NotifyEvent("audio_capture", "stopped");
  if (SUCCEEDED(com_hr)) CoUninitialize();
}
#else
LazyWasapiLoopbackAudio::~LazyWasapiLoopbackAudio() = default;
void LazyWasapiLoopbackAudio::AddRef() const {}
webrtc::RefCountReleaseStatus LazyWasapiLoopbackAudio::Release() const { return webrtc::RefCountReleaseStatus::kOtherRefsRemained; }
webrtc::MediaSourceInterface::SourceState LazyWasapiLoopbackAudio::state() const { return kEnded; }
void LazyWasapiLoopbackAudio::RegisterObserver(webrtc::ObserverInterface*) {}
void LazyWasapiLoopbackAudio::UnregisterObserver(webrtc::ObserverInterface*) {}
void LazyWasapiLoopbackAudio::AddSink(webrtc::AudioTrackSinkInterface*) {}
void LazyWasapiLoopbackAudio::RemoveSink(webrtc::AudioTrackSinkInterface*) {}
bool LazyWasapiLoopbackAudio::Start() { return false; }
void LazyWasapiLoopbackAudio::Stop() {}
void LazyWasapiLoopbackAudio::CaptureLoop() {}
void LazyWasapiLoopbackAudio::Publish(const int16_t*, size_t) {}
#endif



