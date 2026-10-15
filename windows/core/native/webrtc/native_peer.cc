#include "native_peer.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <condition_variable>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "api/create_modular_peer_connection_factory.h"
#include "api/enable_media_with_defaults.h"
#include "api/audio/audio_device.h"
#include "api/audio/create_audio_device_module.h"
#include "api/environment/environment_factory.h"
#include "api/data_channel_interface.h"
#include "api/jsep.h"
#include "api/jsep_ice_candidate.h"
#include "api/make_ref_counted.h"
#include "api/peer_connection_interface.h"
#include "api/scoped_refptr.h"
#include "api/video/i420_buffer.h"
#include "api/video/video_frame.h"
#include "api/video/video_sink_interface.h"
#include "api/video/video_source_interface.h"
#include "modules/desktop_capture/desktop_capture_options.h"
#include "modules/desktop_capture/desktop_capturer.h"
#include "modules/desktop_capture/desktop_frame.h"
#include "pc/video_track_source.h"
#include "rtc_base/thread.h"
#include "rtc_base/time_utils.h"
#include "rtc_base/logging.h"
#include "third_party/libyuv/include/libyuv/convert.h"
#include "wasapi_loopback_audio.h"
#include "rtc_base/win32_socket_init.h"

namespace {

std::unique_ptr<webrtc::Thread> g_network_thread;
std::unique_ptr<webrtc::Thread> g_signaling_thread;
std::unique_ptr<webrtc::WinsockInitializer> g_winsock_initializer;

webrtc::scoped_refptr<webrtc::PeerConnectionFactoryInterface>
    g_peer_connection_factory;

webrtc::scoped_refptr<webrtc::PeerConnectionInterface> g_peer_connection;

webrtc::scoped_refptr<webrtc::DataChannelInterface> g_control_channel;

webrtc::scoped_refptr<webrtc::VideoTrackSourceInterface> g_video_source;
webrtc::scoped_refptr<webrtc::VideoTrackInterface> g_video_track;

webrtc::scoped_refptr<LazyWasapiLoopbackAudio> g_audio_source;
webrtc::scoped_refptr<webrtc::AudioTrackInterface> g_audio_track;

// Screen capture is disabled until the Python security flow explicitly opens
// the Stage 3 hardware-session gate.
std::atomic<bool> g_video_enabled{false};
std::atomic<bool> g_audio_enabled{false};

bool g_initialized = false;

void PushEvent(std::string type, std::string data = {}, bool binary = false);

void CloseTrace(const char* stage) {
  std::fprintf(stderr, "[NATIVE-CLOSE] %s\n", stage);
  std::fflush(stderr);
}

// Small local frame broadcaster. This avoids depending on the optional
// media/base VideoBroadcaster implementation in WebRTC checkouts where that
// target/header is not present. Holding the lock while dispatching also makes
// RemoveSink wait until any in-flight OnFrame call has completed.
class LazyFrameBroadcaster final
    : public webrtc::VideoSourceInterface<webrtc::VideoFrame> {
 public:
  void AddOrUpdateSink(
      webrtc::VideoSinkInterface<webrtc::VideoFrame>* sink,
      const webrtc::VideoSinkWants& /* wants */) override {
    if (!sink) return;
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto* existing : sinks_) {
      if (existing == sink) return;
    }
    sinks_.push_back(sink);
  }

  void RemoveSink(
      webrtc::VideoSinkInterface<webrtc::VideoFrame>* sink) override {
    std::lock_guard<std::mutex> lock(mutex_);
    sinks_.erase(std::remove(sinks_.begin(), sinks_.end(), sink), sinks_.end());
  }

  void OnFrame(const webrtc::VideoFrame& frame) {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto* sink : sinks_) {
      sink->OnFrame(frame);
    }
  }

 private:
  std::mutex mutex_;
  std::vector<webrtc::VideoSinkInterface<webrtc::VideoFrame>*> sinks_;
};

// Captures the primary Windows display and forwards frames into WebRTC's
// video-source pipeline. The capturer is created, used, and destroyed on the
// same dedicated thread, as required by DesktopCapturer.
class LazyDesktopVideoSource : public webrtc::VideoTrackSource,
                                    public webrtc::DesktopCapturer::Callback {
 public:
  LazyDesktopVideoSource() : webrtc::VideoTrackSource(/* is_screencast = */ true) {}
  ~LazyDesktopVideoSource() override { StopCapture(); }

  bool StartCapture() {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
      return true;
    }
    capture_thread_ = std::thread([this] { CaptureLoop(); });
    return true;
  }

  void StopCapture() {
    running_.store(false);
    if (capture_thread_.joinable() &&
        capture_thread_.get_id() != std::this_thread::get_id()) {
      capture_thread_.join();
    }
  }

  bool is_screencast() const override { return true; }
  absl::optional<bool> needs_denoising() const override { return false; }

 protected:
  webrtc::VideoSourceInterface<webrtc::VideoFrame>* source() override {
    return &broadcaster_;
  }

 private:
  void OnCaptureResult(webrtc::DesktopCapturer::Result result,
                       std::unique_ptr<webrtc::DesktopFrame> frame) override {
    if (result != webrtc::DesktopCapturer::Result::SUCCESS || !frame ||
        !frame->data()) {
      return;
    }

    const int width = frame->size().width();
    const int height = frame->size().height();
    if (width < 2 || height < 2) {
      return;
    }

    auto buffer = webrtc::I420Buffer::Create(width, height);
    const int convert_result = libyuv::ConvertToI420(
        frame->data(), static_cast<size_t>(frame->stride()) * height,
        buffer->MutableDataY(), buffer->StrideY(),
        buffer->MutableDataU(), buffer->StrideU(),
        buffer->MutableDataV(), buffer->StrideV(),
        0, 0, width, height, width, height, libyuv::kRotate0,
        static_cast<uint32_t>(frame->pixel_format()));
    if (convert_result != 0) {
      PushEvent("video_error", "bgra_to_i420_failed:" +
                                   std::to_string(convert_result));
      return;
    }

    webrtc::VideoFrame video_frame =
        webrtc::VideoFrame::Builder()
            .set_video_frame_buffer(buffer)
            .set_timestamp_us(std::chrono::duration_cast<std::chrono::microseconds>(
                                   std::chrono::steady_clock::now().time_since_epoch())
                                   .count())
            .build();
    broadcaster_.OnFrame(video_frame);
  }

  void CaptureLoop() {
    webrtc::DesktopCaptureOptions options =
        webrtc::DesktopCaptureOptions::CreateDefault();
    auto capturer = webrtc::DesktopCapturer::CreateScreenCapturer(options);
    if (!capturer) {
      PushEvent("video_error", "screen_capturer_create_failed");
      running_.store(false);
      return;
    }

    webrtc::DesktopCapturer::SourceList sources;
    if (!capturer->GetSourceList(&sources) || sources.empty()) {
      PushEvent("video_error", "no_screen_source_available");
      running_.store(false);
      return;
    }
    if (!capturer->SelectSource(sources.front().id)) {
      PushEvent("video_error", "screen_source_select_failed");
      running_.store(false);
      return;
    }

    capturer->Start(this);
    PushEvent("video_capture", "started");

    auto next_frame = std::chrono::steady_clock::now();
    while (running_.load()) {
      capturer->CaptureFrame();
      next_frame += std::chrono::milliseconds(33);
      std::this_thread::sleep_until(next_frame);
      // Avoid a long catch-up loop if desktop capture temporarily stalls.
      if (std::chrono::steady_clock::now() - next_frame >
          std::chrono::milliseconds(100)) {
        next_frame = std::chrono::steady_clock::now();
      }
    }
    PushEvent("video_capture", "stopped");
  }

  std::atomic<bool> running_{false};
  std::thread capture_thread_;
  LazyFrameBroadcaster broadcaster_;
};

struct Event {
  std::string type;
  std::string data;
  bool binary = false;
};

std::mutex g_event_mutex;
std::deque<Event> g_events;

void PushEvent(std::string type, std::string data, bool binary) {
  std::lock_guard<std::mutex> lock(g_event_mutex);

  constexpr size_t kMaxEvents = 2048;
  if (g_events.size() >= kMaxEvents) {
    g_events.pop_front();
  }

  g_events.push_back(Event{std::move(type), std::move(data), binary});
}

class LazyDataChannelObserver : public webrtc::DataChannelObserver {
 public:
  explicit LazyDataChannelObserver(
      webrtc::scoped_refptr<webrtc::DataChannelInterface> channel)
      : channel_(std::move(channel)) {}

  ~LazyDataChannelObserver() override = default;

  void OnStateChange() override {
    const auto state = channel_->state();

    PushEvent("datachannel_state",
              webrtc::DataChannelInterface::DataStateString(state));
  }

  void OnMessage(const webrtc::DataBuffer& buffer) override {
    std::string data(buffer.data.data<char>(), buffer.data.size());

    PushEvent("datachannel_message", std::move(data), buffer.binary);
  }

  void OnBufferedAmountChange(uint64_t /* previous_amount */) override {}

 private:
  webrtc::scoped_refptr<webrtc::DataChannelInterface> channel_;
};

std::unique_ptr<LazyDataChannelObserver> g_control_observer;

class LazyPeerConnectionObserver : public webrtc::PeerConnectionObserver {
 public:
  LazyPeerConnectionObserver() = default;
  ~LazyPeerConnectionObserver() override = default;

  void OnSignalingChange(
      webrtc::PeerConnectionInterface::SignalingState new_state) override {
    PushEvent("signaling_state", std::to_string(static_cast<int>(new_state)));
  }

  void OnAddStream(
      webrtc::scoped_refptr<webrtc::MediaStreamInterface> /* stream */)
      override {}

  void OnRemoveStream(
      webrtc::scoped_refptr<webrtc::MediaStreamInterface> /* stream */)
      override {}

  void OnDataChannel(
      webrtc::scoped_refptr<webrtc::DataChannelInterface> channel) override {
    if (channel->label() != "control") {
      return;
    }

    g_control_channel = channel;

    g_control_observer = std::make_unique<LazyDataChannelObserver>(channel);

    channel->RegisterObserver(g_control_observer.get());

    PushEvent("datachannel", "control");
  }

  void OnRenegotiationNeeded() override { PushEvent("renegotiation_needed"); }

  void OnIceConnectionChange(
      webrtc::PeerConnectionInterface::IceConnectionState new_state) override {
    PushEvent("ice_connection_state",
              std::to_string(static_cast<int>(new_state)));
  }

  void OnIceGatheringChange(
      webrtc::PeerConnectionInterface::IceGatheringState new_state) override {
    PushEvent("ice_gathering_state",
              std::to_string(static_cast<int>(new_state)));
  }

  void OnIceCandidate(const webrtc::IceCandidateInterface* candidate) override {
    if (!candidate) {
      return;
    }

    std::string sdp;
    candidate->ToString(&sdp);

    // Format:
    // sdp_mid
    // sdp_mline_index
    // candidate_sdp
    //
    // Candidate SDP itself does not contain newlines,
    // so this is safe for our internal event transport.
    std::string payload = candidate->sdp_mid() + "\n" +
                          std::to_string(candidate->sdp_mline_index()) + "\n" +
                          sdp;

    PushEvent("ice_candidate", payload, false);
  }

  void OnIceConnectionReceivingChange(bool receiving) override {
    PushEvent("ice_receiving", receiving ? "1" : "0");
  }

  void OnTrack(
      webrtc::scoped_refptr<webrtc::RtpTransceiverInterface> /* transceiver */)
      override {}

  void OnRemoveTrack(
      webrtc::scoped_refptr<webrtc::RtpReceiverInterface> /* receiver */)
      override {}

  void OnInterestingUsage(int /* usage_pattern */) override {}
};

std::unique_ptr<LazyPeerConnectionObserver> g_peer_observer;

void CleanupControlChannel() {
  if (g_control_channel) {
    g_control_channel->UnregisterObserver();
  }

  g_control_observer.reset();
  g_control_channel = nullptr;
}

void CleanupThreads() {
  CloseTrace("CleanupThreads: enter");

  // The PeerConnectionFactory and media references must already be released
  // while both WebRTC threads are alive. Stop the network thread first so
  // pending network-side teardown can still interact with the signaling
  // thread; stop signaling only after network shutdown has completed.
  if (g_network_thread) {
    CloseTrace("CleanupThreads: before network Stop");
    g_network_thread->Stop();
    CloseTrace("CleanupThreads: after network Stop; before reset");
    g_network_thread.reset();
    CloseTrace("CleanupThreads: network thread reset");
  }

  if (g_signaling_thread) {
    CloseTrace("CleanupThreads: before signaling Stop");
    g_signaling_thread->Stop();
    CloseTrace("CleanupThreads: after signaling Stop; before reset");
    g_signaling_thread.reset();
    CloseTrace("CleanupThreads: signaling thread reset");
  }

  // Winsock must remain initialized until both WebRTC threads have stopped.
  CloseTrace("CleanupThreads: before Winsock reset");
  g_winsock_initializer.reset();
  CloseTrace("CleanupThreads: complete");
}

class BlockingCreateDescriptionObserver
    : public webrtc::CreateSessionDescriptionObserver {
 public:
  BlockingCreateDescriptionObserver() = default;

  void OnSuccess(webrtc::SessionDescriptionInterface* description) override {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (description) {
        description_.reset(description);
        description->ToString(&sdp_);
        success_ = true;
      } else {
        error_ = "CreateSessionDescription returned null";
      }
      done_ = true;
    }
    condition_.notify_one();
  }

  void OnFailure(webrtc::RTCError error) override {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      error_ = error.message();
      done_ = true;
    }
    condition_.notify_one();
  }

  std::unique_ptr<webrtc::SessionDescriptionInterface> TakeDescription() {
    std::lock_guard<std::mutex> lock(mutex_);
    return std::move(description_);
  }

  bool Wait(std::string* out_sdp, std::string* out_error) {
    std::unique_lock<std::mutex> lock(mutex_);

    condition_.wait(lock, [this] { return done_; });

    if (!success_) {
      if (out_error) {
        *out_error = error_;
      }
      return false;
    }

    if (out_sdp) {
      *out_sdp = sdp_;
    }

    return true;
  }

 private:
  std::mutex mutex_;
  std::condition_variable condition_;

  bool done_ = false;
  bool success_ = false;

  std::string sdp_;
  std::string error_;

  std::unique_ptr<webrtc::SessionDescriptionInterface> description_;
};

class BlockingSetDescriptionObserver
    : public webrtc::SetSessionDescriptionObserver {
 public:
  BlockingSetDescriptionObserver() = default;

  void OnSuccess() override {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      success_ = true;
      done_ = true;
    }
    condition_.notify_one();
  }

  void OnFailure(webrtc::RTCError error) override {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      error_ = error.message();
      done_ = true;
    }
    condition_.notify_one();
  }

  bool Wait(std::string* out_error) {
    std::unique_lock<std::mutex> lock(mutex_);

    condition_.wait(lock, [this] { return done_; });

    if (!success_) {
      if (out_error) {
        *out_error = error_;
      }
      return false;
    }

    return true;
  }

 private:
  std::mutex mutex_;
  std::condition_variable condition_;

  bool done_ = false;
  bool success_ = false;
  std::string error_;
};

webrtc::SdpType ParseSdpType(const char* type) {
  if (!type) {
    return webrtc::SdpType::kOffer;
  }

  const std::string value(type);

  if (value == "answer") {
    return webrtc::SdpType::kAnswer;
  }

  if (value == "pranswer") {
    return webrtc::SdpType::kPrAnswer;
  }

  return webrtc::SdpType::kOffer;
}
char* DuplicateString(const std::string& value) {
  const size_t size = value.size();

  char* result = static_cast<char*>(std::malloc(size + 1));

  if (!result) {
    return nullptr;
  }

  std::memcpy(result, value.data(), size + 1);

  return result;
}

bool SetLocalDescriptionInternal(const std::string& type,
                                 const std::string& sdp) {
  if (!g_peer_connection || !g_signaling_thread) {
    return false;
  }

  auto description =
      webrtc::CreateSessionDescription(ParseSdpType(type.c_str()), sdp);

  if (!description) {
    return false;
  }

  auto observer = webrtc::make_ref_counted<BlockingSetDescriptionObserver>();

  g_signaling_thread->BlockingCall(
      [description = std::move(description), observer]() mutable {
        g_peer_connection->SetLocalDescription(observer.get(),
                                               description.release());
      });

  std::string error;
  return observer->Wait(&error);
}

bool SetRemoteDescriptionInternal(const std::string& type,
                                  const std::string& sdp) {
  if (!g_peer_connection || !g_signaling_thread) {
    return false;
  }

  auto description =
      webrtc::CreateSessionDescription(ParseSdpType(type.c_str()), sdp);

  if (!description) {
    return false;
  }

  auto observer = webrtc::make_ref_counted<BlockingSetDescriptionObserver>();

  g_signaling_thread->BlockingCall(
      [description = std::move(description), observer]() mutable {
        g_peer_connection->SetRemoteDescription(observer.get(),
                                                description.release());
      });

  std::string error;
  return observer->Wait(&error);
}

}  // namespace

extern "C" {

int lazypc_webrtc_init() {
  // Reduce WebRTC console noise while retaining actual errors.
  // This checkout exposes the logging API in namespace `webrtc` (not `rtc`).
  webrtc::LoggingConfig logging_config;
  logging_config.set_min_severity(webrtc::LS_ERROR);
  logging_config.set_debug_severity(webrtc::LS_ERROR);
  logging_config.set_log_to_stderr(true);
  (void)webrtc::InitializeLogging(std::move(logging_config));
  if (g_initialized) {
    return 1;
  }

  // Initialize Winsock before creating WebRTC's socket server/network thread.
  g_winsock_initializer =
      std::make_unique<webrtc::WinsockInitializer>();
  if (g_winsock_initializer->error() != 0) {
    PushEvent("error", "winsock_initialization_failed");
    g_winsock_initializer.reset();
    return 0;
  }

  g_network_thread = webrtc::Thread::CreateWithSocketServer();

  g_signaling_thread = webrtc::Thread::Create();

  if (!g_network_thread || !g_signaling_thread) {
    CleanupThreads();
    return 0;
  }

  if (!g_network_thread->Start() || !g_signaling_thread->Start()) {
    CleanupThreads();
    return 0;
  }

  webrtc::PeerConnectionFactoryDependencies dependencies;
  dependencies.network_thread = g_network_thread.get();
  dependencies.signaling_thread = g_signaling_thread.get();

  // LazyPC captures system output through LazyWasapiLoopbackAudio. It does not
  // use WebRTC's physical microphone capture path. Supply WebRTC's dummy ADM
  // so its media engine does not enumerate/open a Windows recording device.
  // This does not replace the custom WASAPI loopback source attached to the
  // outgoing audio track below; that source remains responsible for system audio.
  dependencies.env = webrtc::CreateEnvironment();
  dependencies.adm = webrtc::CreateAudioDeviceModule(
      *dependencies.env, webrtc::AudioDeviceModule::kDummyAudio);
  if (!dependencies.adm) {
    PushEvent("error", "dummy_audio_device_module_creation_failed");
    CleanupThreads();
    return 0;
  }

  // The modular factory is intentionally media-disabled unless media
  // dependencies are configured. LazyPC sends desktop video and system audio
  // tracks, so install WebRTC's built-in codec/media factories while keeping
  // the physical recording device out of the configuration.
  webrtc::EnableMediaWithDefaults(dependencies);

  if (!dependencies.media_factory) {
    PushEvent("error", "media_factory_is_null_before_create");
    CleanupThreads();
    return 0;
  }

  g_peer_connection_factory =
      webrtc::CreateModularPeerConnectionFactory(std::move(dependencies));

  if (!g_peer_connection_factory) {
    CleanupThreads();
    return 0;
  }

  g_initialized = true;

  PushEvent("initialized", "1");
  return 1;
}

void lazypc_webrtc_shutdown() {
  CloseTrace("shutdown: enter");
  if (!g_initialized) {
    CloseTrace("shutdown: already uninitialized; return");
    return;
  }

  CloseTrace("shutdown: before CleanupControlChannel");
  CleanupControlChannel();
  CloseTrace("shutdown: after CleanupControlChannel");

  g_video_enabled.store(false);
  if (g_video_track) g_video_track->set_enabled(false);
  CloseTrace("shutdown: video track disabled");
  if (g_video_source) {
    CloseTrace("shutdown: before video StopCapture");
    auto* source = static_cast<LazyDesktopVideoSource*>(g_video_source.get());
    source->StopCapture();
    CloseTrace("shutdown: after video StopCapture");
  }
  g_audio_enabled.store(false);
  if (g_audio_track) g_audio_track->set_enabled(false);
  CloseTrace("shutdown: audio track disabled");
  if (g_audio_source) {
    CloseTrace("shutdown: before WASAPI Stop");
    g_audio_source->Stop();
    CloseTrace("shutdown: after WASAPI Stop");
  }
  if (g_peer_connection) {
    CloseTrace("shutdown: before PeerConnection::Close");
    g_peer_connection->Close();
    CloseTrace("shutdown: after PeerConnection::Close");
  }

  CloseTrace("shutdown: before resetting peer/media refs");
  // Release PeerConnection and its media objects while WebRTC's signaling
  // thread is still alive. The factory can schedule cleanup on WebRTC threads,
  // so release it on the signaling thread before stopping either thread.
  if (g_signaling_thread) {
    g_signaling_thread->BlockingCall([]() {
      g_peer_connection = nullptr;
      g_video_track = nullptr;
      g_video_source = nullptr;
      g_audio_track = nullptr;
      g_audio_source = nullptr;
      g_peer_observer.reset();
      CloseTrace("shutdown: media refs reset; before factory reset");
      g_peer_connection_factory = nullptr;
      CloseTrace("shutdown: factory reset on signaling thread");
    });
  } else {
    g_peer_connection = nullptr;
    g_video_track = nullptr;
    g_video_source = nullptr;
    g_audio_track = nullptr;
    g_audio_source = nullptr;
    g_peer_observer.reset();
    g_peer_connection_factory = nullptr;
  }
  CloseTrace("shutdown: before CleanupThreads");

  CleanupThreads();

  CloseTrace("shutdown: before clearing events");
  {
    std::lock_guard<std::mutex> lock(g_event_mutex);
    g_events.clear();
  }

  g_initialized = false;
  CloseTrace("shutdown: complete");
}

int lazypc_webrtc_is_initialized() {
  return g_initialized ? 1 : 0;
}

int lazypc_webrtc_create_peer_connection() {
  if (!g_initialized || !g_peer_connection_factory || !g_signaling_thread) {
    return 0;
  }

  if (g_peer_connection) {
    return 1;
  }

  g_video_enabled.store(false);
  int result = 0;

  g_signaling_thread->BlockingCall([&]() {
    g_peer_observer = std::make_unique<LazyPeerConnectionObserver>();

    webrtc::PeerConnectionInterface::RTCConfiguration config;

    webrtc::PeerConnectionDependencies dependencies(g_peer_observer.get());

    auto peer_result = g_peer_connection_factory->CreatePeerConnectionOrError(
        config, std::move(dependencies));

    if (!peer_result.ok()) {
      g_peer_observer.reset();
      return;
    }

    g_peer_connection = peer_result.MoveValue();

    auto video_source = webrtc::make_ref_counted<LazyDesktopVideoSource>();
    auto video_track = g_peer_connection_factory->CreateVideoTrack(
        video_source, "lazypc-screen");
    if (!video_track) {
      PushEvent("error", "create_video_track_failed");
      g_peer_connection->Close();
      g_peer_connection = nullptr;
      return;
    }

    auto add_track_result = g_peer_connection->AddTrack(
        video_track, std::vector<std::string>{"lazypc-stream"});
    if (!add_track_result.ok()) {
      PushEvent("error", std::string("add_video_track:") +
                              add_track_result.error().message());
      g_peer_connection->Close();
      g_peer_connection = nullptr;
      return;
    }

    // Add an audio m-line before SDP creation, but keep capture muted until
    // Stage 3 authorization explicitly opens the audio gate.
    auto audio_source = webrtc::scoped_refptr<LazyWasapiLoopbackAudio>(
        new LazyWasapiLoopbackAudio());
    audio_source->SetEventCallback([](const char* type, const char* data) {
      PushEvent(type ? type : "audio_event", data ? data : "");
    });
    auto audio_track = g_peer_connection_factory->CreateAudioTrack(
        "lazypc-system-audio", audio_source.get());
    if (!audio_track) {
      PushEvent("audio_error", "create_audio_track_failed");
      g_peer_connection->Close();
      g_peer_connection = nullptr;
      return;
    }
    auto add_audio_result = g_peer_connection->AddTrack(
        audio_track, std::vector<std::string>{"lazypc-stream"});
    if (!add_audio_result.ok()) {
      PushEvent("audio_error", std::string("add_audio_track:") +
                                    add_audio_result.error().message());
      g_peer_connection->Close();
      g_peer_connection = nullptr;
      return;
    }

    g_video_source = video_source;
    g_video_track = video_track;
    g_audio_source = audio_source;
    g_audio_track = audio_track;
    g_video_enabled.store(false);
    g_audio_enabled.store(false);
    g_video_track->set_enabled(false);
    g_audio_track->set_enabled(false);
    // Do not start desktop or WASAPI capture here. Stage 3 opens both gates.
    PushEvent("video_track", "screen_added_disabled");
    PushEvent("audio_track", "system_audio_added_disabled");
    result = 1;
  });

  if (result) {
    PushEvent("peer_connection", "created");
  }

  return result;
}

int lazypc_webrtc_set_video_enabled(int enabled) {
  if (!g_peer_connection || !g_signaling_thread || !g_video_track || !g_video_source) {
    return 0;
  }

  const bool should_enable = enabled != 0;
  int result = 0;
  g_signaling_thread->BlockingCall([&]() {
    auto* source = static_cast<LazyDesktopVideoSource*>(g_video_source.get());
    if (!should_enable) {
      // Close media gates together when Stage 3 is revoked.
      g_video_enabled.store(false);
      g_video_track->set_enabled(false);
      source->StopCapture();

      if (g_audio_track && g_audio_source) {
        g_audio_enabled.store(false);
        g_audio_track->set_enabled(false);
        g_audio_source->Stop();
        PushEvent("audio_gate", "disabled");
      }

      PushEvent("video_gate", "disabled");
      result = 1;
      return;
    }

    g_video_track->set_enabled(true);
    g_video_enabled.store(true);
    if (!source->StartCapture()) {
      g_video_track->set_enabled(false);
      g_video_enabled.store(false);
      PushEvent("video_error", "screen_capture_start_failed");
      return;
    }

    // Stage 3 opens both protected media paths. System audio is captured
    // with WASAPI loopback, not the microphone recording device.
    if (!g_audio_track || !g_audio_source) {
      source->StopCapture();
      g_video_track->set_enabled(false);
      g_video_enabled.store(false);
      PushEvent("audio_error", "audio_track_not_available");
      return;
    }

    g_audio_track->set_enabled(true);
    if (!g_audio_source->Start()) {
      g_audio_track->set_enabled(false);
      source->StopCapture();
      g_video_track->set_enabled(false);
      g_video_enabled.store(false);
      g_audio_enabled.store(false);
      PushEvent("audio_error", "wasapi_loopback_start_failed");
      return;
    }
    g_audio_enabled.store(true);
    PushEvent("audio_gate", "enabled");

    PushEvent("video_gate", "enabled");
    result = 1;
  });
  return result;
}

int lazypc_webrtc_set_audio_enabled(int enabled) {
  if (!g_peer_connection || !g_signaling_thread || !g_audio_track || !g_audio_source) {
    PushEvent("audio_error", "audio_track_not_available");
    return 0;
  }

  const bool should_enable = enabled != 0;
  int result = 0;
  g_signaling_thread->BlockingCall([&]() {
    if (!should_enable) {
      g_audio_enabled.store(false);
      g_audio_track->set_enabled(false);
      g_audio_source->Stop();
      PushEvent("audio_gate", "disabled");
      result = 1;
      return;
    }

    g_audio_track->set_enabled(true);
    if (!g_audio_source->Start()) {
      g_audio_track->set_enabled(false);
      g_audio_enabled.store(false);
      PushEvent("audio_error", "wasapi_loopback_start_failed");
      return;
    }
    g_audio_enabled.store(true);
    PushEvent("audio_gate", "enabled");
    result = 1;
  });
  return result;
}

void lazypc_webrtc_close_peer_connection() {
  CloseTrace("enter close_peer_connection");
  if (!g_peer_connection) {
    CloseTrace("no peer connection; return");
    return;
  }

  if (g_signaling_thread) {
    CloseTrace("before signaling BlockingCall");
    g_signaling_thread->BlockingCall([]() {
      CloseTrace("inside signaling BlockingCall");
      CloseTrace("before CleanupControlChannel");
      CleanupControlChannel();
      CloseTrace("after CleanupControlChannel");
      g_video_enabled.store(false);
      if (g_video_track) g_video_track->set_enabled(false);
      CloseTrace("video track disabled");

      if (g_video_source) {
        CloseTrace("before video StopCapture");
        auto* source = static_cast<LazyDesktopVideoSource*>(g_video_source.get());
        source->StopCapture();
        CloseTrace("after video StopCapture");
      }
      g_audio_enabled.store(false);
      if (g_audio_track) g_audio_track->set_enabled(false);
      CloseTrace("audio track disabled");
      if (g_audio_source) {
        CloseTrace("before WASAPI Stop");
        g_audio_source->Stop();
        CloseTrace("after WASAPI Stop");
      }
      if (g_peer_connection) {
        CloseTrace("before PeerConnection::Close");
        g_peer_connection->Close();
        CloseTrace("after PeerConnection::Close");
      }

      CloseTrace("before resetting peer/media refs");
      g_peer_connection = nullptr;
      g_video_track = nullptr;
      g_video_source = nullptr;
      g_audio_track = nullptr;
      g_audio_source = nullptr;
      CloseTrace("media refs reset; before observer reset");
      g_peer_observer.reset();
      CloseTrace("observer reset; signaling callback done");
    });
    CloseTrace("after signaling BlockingCall");
  } else {
    CloseTrace("signaling thread missing; fallback cleanup");
    CleanupControlChannel();
    g_video_enabled.store(false);
    if (g_video_track) g_video_track->set_enabled(false);
    if (g_video_source) {
      auto* source = static_cast<LazyDesktopVideoSource*>(g_video_source.get());
      source->StopCapture();
    }
    g_audio_enabled.store(false);
    if (g_audio_track) g_audio_track->set_enabled(false);
    if (g_audio_source) g_audio_source->Stop();
    g_peer_connection = nullptr;
    g_video_track = nullptr;
    g_video_source = nullptr;
    g_audio_track = nullptr;
    g_audio_source = nullptr;
    g_peer_observer.reset();
    CloseTrace("fallback cleanup done");
  }

  CloseTrace("before closed event");
  PushEvent("peer_connection", "closed");
  CloseTrace("close_peer_connection finished");
}

int lazypc_webrtc_has_peer_connection() {
  return g_peer_connection ? 1 : 0;
}

int lazypc_webrtc_create_control_channel() {
  if (!g_peer_connection || !g_signaling_thread) {
    return 0;
  }

  if (g_control_channel) {
    return 1;
  }

  int result = 0;

  g_signaling_thread->BlockingCall([&]() {
    webrtc::DataChannelInit config;

    auto channel_result =
        g_peer_connection->CreateDataChannelOrError("control", &config);

    if (!channel_result.ok()) {
      return;
    }

    g_control_channel = channel_result.MoveValue();

    g_control_observer =
        std::make_unique<LazyDataChannelObserver>(g_control_channel);

    g_control_channel->RegisterObserver(g_control_observer.get());

    result = 1;
  });

  if (result) {
    PushEvent("datachannel", "control");
  }

  return result;
}

int lazypc_webrtc_has_control_channel() {
  return g_control_channel ? 1 : 0;
}

int lazypc_webrtc_create_offer(char** out_sdp) {
  if (!out_sdp || !g_peer_connection || !g_signaling_thread) {
    return 0;
  }

  *out_sdp = nullptr;

  auto observer = webrtc::make_ref_counted<BlockingCreateDescriptionObserver>();

  g_signaling_thread->BlockingCall([observer]() {
    webrtc::PeerConnectionInterface::RTCOfferAnswerOptions options;

    g_peer_connection->CreateOffer(observer.get(), options);
  });

  std::string sdp;
  std::string error;

  if (!observer->Wait(&sdp, &error)) {
    PushEvent("error", "create_offer:" + error);
    return 0;
  }

  auto description = observer->TakeDescription();
  if (!description) {
    PushEvent("error", "create_offer:no_description");
    return 0;
  }

  auto set_observer =
      webrtc::make_ref_counted<BlockingSetDescriptionObserver>();

  g_signaling_thread->BlockingCall(
      [description = std::move(description), set_observer]() mutable {
        g_peer_connection->SetLocalDescription(set_observer.get(),
                                               description.release());
      });

  if (!set_observer->Wait(&error)) {
    PushEvent("error", "set_local_offer:" + error);
    return 0;
  }

  *out_sdp = DuplicateString(sdp);
  return *out_sdp ? 1 : 0;
}

int lazypc_webrtc_create_answer(char** out_sdp) {
  if (!out_sdp || !g_peer_connection || !g_signaling_thread) {
    return 0;
  }

  *out_sdp = nullptr;

  auto observer = webrtc::make_ref_counted<BlockingCreateDescriptionObserver>();

  g_signaling_thread->BlockingCall([observer]() {
    webrtc::PeerConnectionInterface::RTCOfferAnswerOptions options;

    g_peer_connection->CreateAnswer(observer.get(), options);
  });

  std::string sdp;
  std::string error;

  if (!observer->Wait(&sdp, &error)) {
    PushEvent("error", "create_answer:" + error);
    return 0;
  }

  auto description = observer->TakeDescription();
  if (!description) {
    PushEvent("error", "create_answer:no_description");
    return 0;
  }

  auto set_observer =
      webrtc::make_ref_counted<BlockingSetDescriptionObserver>();

  g_signaling_thread->BlockingCall(
      [description = std::move(description), set_observer]() mutable {
        g_peer_connection->SetLocalDescription(set_observer.get(),
                                               description.release());
      });

  if (!set_observer->Wait(&error)) {
    PushEvent("error", "set_local_answer:" + error);
    return 0;
  }

  *out_sdp = DuplicateString(sdp);
  return *out_sdp ? 1 : 0;
}

int lazypc_webrtc_set_remote_description(const char* type, const char* sdp) {
  if (!type || !sdp) {
    return 0;
  }

  return SetRemoteDescriptionInternal(type, sdp) ? 1 : 0;
}

int lazypc_webrtc_set_local_description(const char* type, const char* sdp) {
  if (!type || !sdp) {
    return 0;
  }

  return SetLocalDescriptionInternal(type, sdp) ? 1 : 0;
}

int lazypc_webrtc_add_ice_candidate(const char* sdp_mid,
                                    int sdp_mline_index,
                                    const char* candidate) {
  if (!g_peer_connection || !g_signaling_thread || !sdp_mid || !candidate) {
    return 0;
  }

  std::string mid(sdp_mid);
  std::string candidate_sdp(candidate);

  int result = 0;

  g_signaling_thread->BlockingCall([&]() {
    webrtc::SdpParseError error;

    std::unique_ptr<webrtc::IceCandidateInterface> parsed(
        webrtc::CreateIceCandidate(mid, sdp_mline_index, candidate_sdp,
                                   &error));

    if (!parsed) {
      return;
    }

    result = g_peer_connection->AddIceCandidate(parsed.get()) ? 1 : 0;
  });

  return result;
}

void lazypc_webrtc_free_string(void* ptr) {
  std::free(ptr);
}

int lazypc_webrtc_send_control(const void* data, size_t size, int binary) {
  if (!g_control_channel || !data || size == 0) {
    return 0;
  }

  int result = 0;

  std::string payload(static_cast<const char*>(data), size);

  if (g_signaling_thread) {
    g_signaling_thread->BlockingCall([&]() {
      if (!g_control_channel ||
          g_control_channel->state() != webrtc::DataChannelInterface::kOpen) {
        return;
      }

      webrtc::CopyOnWriteBuffer buffer(payload.data(), payload.size());

      webrtc::DataBuffer message(buffer, binary != 0);

      result = g_control_channel->Send(message) ? 1 : 0;
    });
  }

  return result;
}

int lazypc_webrtc_control_state() {
  if (!g_control_channel) {
    return -1;
  }

  return static_cast<int>(g_control_channel->state());
}

int lazypc_webrtc_next_event(char* event_type,
                             size_t event_type_capacity,
                             char* event_data,
                             size_t event_data_capacity,
                             int* binary) {
  if (!event_type || !event_data || !binary || event_type_capacity == 0 ||
      event_data_capacity == 0) {
    return 0;
  }

  std::lock_guard<std::mutex> lock(g_event_mutex);

  if (g_events.empty()) {
    return 0;
  }

  const Event& event = g_events.front();

  if (event.type.size() + 1 > event_type_capacity ||
      event.data.size() > event_data_capacity) {
    return -1;
  }

  std::memcpy(event_type, event.type.c_str(), event.type.size() + 1);

  if (!event.data.empty()) {
    std::memcpy(event_data, event.data.data(), event.data.size());
  }

  *binary = event.binary ? 1 : 0;

  const int result = static_cast<int>(event.data.size());

  g_events.pop_front();

  return result;
}

}  // extern "C"

