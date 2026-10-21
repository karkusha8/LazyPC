#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <mutex>
#include <thread>
#include <vector>

#include "api/media_stream_interface.h"

// Windows render-device loopback source. Produces signed 16-bit, 48 kHz stereo
// PCM frames to WebRTC audio-track sinks. Capture starts only when Start() is
// called (the Stage 3 gate in the owner controls that call).
class LazyWasapiLoopbackAudio final : public webrtc::AudioSourceInterface {
 public:
  LazyWasapiLoopbackAudio() = default;
  ~LazyWasapiLoopbackAudio() override;

  void AddRef() const override;
  webrtc::RefCountReleaseStatus Release() const override;
  SourceState state() const override;
  bool remote() const override { return false; }
  void RegisterObserver(webrtc::ObserverInterface* observer) override;
  void UnregisterObserver(webrtc::ObserverInterface* observer) override;
  void AddSink(webrtc::AudioTrackSinkInterface* sink) override;
  void RemoveSink(webrtc::AudioTrackSinkInterface* sink) override;

  bool Start();
  void Stop();
  void SetEventCallback(std::function<void(const char*, const char*)> callback);

 private:
  void CaptureLoop();
  void Publish(const int16_t* samples, size_t frames);
  void NotifyEvent(const char* type, const char* data);

  mutable std::atomic<int> refs_{0};
  std::atomic<bool> running_{false};
  std::atomic<SourceState> state_{kInitializing};
  std::thread thread_;
  std::mutex mutex_;
  std::vector<webrtc::AudioTrackSinkInterface*> sinks_;
  std::vector<webrtc::ObserverInterface*> observers_;
  std::function<void(const char*, const char*)> event_callback_;
};



