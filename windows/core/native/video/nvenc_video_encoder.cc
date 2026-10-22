#include "nvenc_video_encoder.h"

#ifdef _WIN32
#include <windows.h>
#include <d3d11.h>
#include <d3d10.h>
#include <dxgi.h>
#include <wrl/client.h>
#endif

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <iterator>
#include <string>
#include <utility>
#include <vector>

#include "api/video/encoded_image.h"
#include "api/video/i420_buffer.h"
#include "api/video_codecs/sdp_video_format.h"
#include "api/video_codecs/video_codec.h"
#include "api/video_codecs/video_encoder.h"
#include "api/video_codecs/video_encoder_factory.h"
#include "modules/video_coding/include/video_codec_interface.h"
#include "api/environment/environment.h"
#include "third_party/nvcodec/nvEncodeAPI.h"
#include "third_party/libyuv/include/libyuv/convert.h"
#include "d3d11_video_processor.h"
#include "modules/desktop_capture/win/dxgi_gpu_frame_observer.h"

namespace {

// WebRTC's legacy WEBRTC_VIDEO_CODEC_* constants are absent in this checkout.
// Keep the established VideoEncoder return-code values locally.
constexpr int32_t kVideoCodecOk = 0;
constexpr int32_t kVideoCodecError = -1;
constexpr int32_t kVideoCodecUninitialized = -3;
constexpr int32_t kVideoCodecErrParameter = -4;

#ifdef _WIN32
using Microsoft::WRL::ComPtr;

const D3D_FEATURE_LEVEL* GetFeatureLevelsAfterFirst(const D3D_FEATURE_LEVEL* levels) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wunsafe-buffer-usage"
  const D3D_FEATURE_LEVEL* result = levels + 1;
#pragma clang diagnostic pop
  return result;
}

// Holds the D3D11 device lock (ID3D10Multithread::Enter/Leave). NVENC talks to
// the driver directly, so D3D11's per-call locking does not cover the whole
// VideoProcessorBlt -> nvEncMapInputResource -> nvEncEncodePicture sequence.
// Without holding the device lock across it, the DXGI capture thread
// (CopyResource/CreateTexture2D on the same immediate context) interleaves and
// the driver can deadlock inside nvEncMapInputResource.
class D3dDeviceLock {
 public:
  explicit D3dDeviceLock(ID3D10Multithread* mt) : mt_(mt) { Lock(); }
  ~D3dDeviceLock() { Unlock(); }
  D3dDeviceLock(const D3dDeviceLock&) = delete;
  D3dDeviceLock& operator=(const D3dDeviceLock&) = delete;
  void Lock() {
    if (mt_ && !held_) {
      mt_->Enter();
      held_ = true;
    }
  }
  void Unlock() {
    if (mt_ && held_) {
      mt_->Leave();
      held_ = false;
    }
  }

 private:
  ID3D10Multithread* mt_;
  bool held_ = false;
};

class NvencEncoder final : public webrtc::VideoEncoder {
 public:
  ~NvencEncoder() override { Release(); }

  int32_t InitEncode(const webrtc::VideoCodec* codec,
                     const Settings& settings) override {
    std::lock_guard<std::mutex> lock(mutex_);
    ReleaseLocked();
    if (!codec || codec->codecType != webrtc::kVideoCodecH264 ||
        codec->width < 2 || codec->height < 2) {
      return kVideoCodecErrParameter;
    }
    width_ = static_cast<uint32_t>(codec->width);
    height_ = static_cast<uint32_t>(codec->height);
    fps_ = std::max<uint32_t>(1, codec->maxFramerate);
    bitrate_bps_ = std::max<uint32_t>(500000, codec->startBitrate * 1000);
    std::fprintf(stderr, "[LazyPC-VIDEO] NVENC InitEncode requested: codec=H264 size=%ux%u fps=%u bitrate=%u bps\n",
                 width_, height_, fps_, bitrate_bps_);
    std::fflush(stderr);
    if (!LoadApiLocked()) {
      std::fprintf(stderr, "[LazyPC-VIDEO] ERROR: NVENC API load failed (nvEncodeAPI64.dll / NvEncodeAPICreateInstance)\n");
      std::fflush(stderr);
      ReleaseLocked();
      return kVideoCodecError;
    }
    // Defer opening the NVENC session until Encode() can select the actual
    // DXGI capture device. NVENC D3D11 resources must belong to the device used
    // to open the session; opening on a second device would defeat zero-copy.
    initialized_ = true;
    gpu_init_wait_frames_ = 0;
    gpu_path_logged_ = false;
    webrtc::EnableDxgiGpuFrameQueue(true);
    std::fprintf(stderr,
                 "[LazyPC-VIDEO] NVENC API ready; waiting for DXGI GPU frame to select D3D11 device\n");
    std::fflush(stderr);
    return kVideoCodecOk;
  }

  int32_t RegisterEncodeCompleteCallback(
      webrtc::EncodedImageCallback* callback) override {
    std::lock_guard<std::mutex> lock(mutex_);
    callback_ = callback;
    return kVideoCodecOk;
  }

  int32_t Release() override {
    std::lock_guard<std::mutex> lock(mutex_);
    ReleaseLocked();
    return kVideoCodecOk;
  }

  int32_t Encode(const webrtc::VideoFrame& frame,
                 const std::vector<webrtc::VideoFrameType>* frame_types) override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!initialized_ || !callback_) return kVideoCodecUninitialized;

    const bool gpu_only_capture = webrtc::IsDxgiGpuOnlyCaptureEnabled();
    webrtc::DxgiGpuFrame gpu_frame;
    const bool have_new_gpu_frame = TryPopDxgiGpuFrame(&gpu_frame);
    if (have_new_gpu_frame) {
      // Retain the most recent owned DXGI texture. Desktop Duplication only
      // publishes a new texture when the desktop changes; WebRTC still asks
      // the encoder for frames at its target cadence. Reuse the last captured
      // texture between updates instead of dropping every frame on an empty
      // queue (which starves the remote video stream).
      last_gpu_frame_ = gpu_frame;
      have_last_gpu_frame_ = true;
    } else if (gpu_only_capture && have_last_gpu_frame_ &&
               last_gpu_frame_.texture && last_gpu_frame_.device) {
      gpu_frame = last_gpu_frame_;
    }
    const bool have_gpu_frame = have_new_gpu_frame ||
        (gpu_only_capture && have_last_gpu_frame_ && gpu_frame.texture && gpu_frame.device);
    if (!encoder_) {
      bool opened = false;
      if (have_gpu_frame && gpu_frame.device) {
        opened = OpenEncoderOnDeviceLocked(gpu_frame.device.Get());
        if (!opened) {
          CloseEncoderSessionLocked();
          std::fprintf(stderr,
                       "[LazyPC-GPU] NVENC could not open on DXGI device; trying CPU-fallback device\n");
          std::fflush(stderr);
        }
      }
      // The DXGI observer is normally called before the corresponding CPU
      // DesktopFrame reaches WebRTC. Allow a short startup window for it. If
      // GPU capture is unavailable, preserve the established CPU input path.
      if (!opened && !have_gpu_frame && gpu_init_wait_frames_++ < 12) {
        return kVideoCodecOk;
      }
      if (!opened) {
        if (!CreateD3DDeviceLocked() ||
            !OpenEncoderOnDeviceLocked(d3d_device_.Get())) {
          CloseEncoderSessionLocked();
          return kVideoCodecError;
        }
      }
      std::fprintf(stderr,
                   "[LazyPC-VIDEO] NVENC session opened; device selected from %s\n",
                   have_gpu_frame ? "DXGI capture frame" : "CPU fallback path");
      std::fflush(stderr);
    }

    const uint64_t encoded_before_gpu_attempt = encoded_frames_;
    if (have_gpu_frame && EncodeGpuFrameLocked(gpu_frame, frame, frame_types)) {
      // Do not switch capture to zero-readback just because NVENC accepted an
      // input. NVENC can return NEED_MORE_INPUT without producing a bitstream;
      // GPU-only mode is safe only after a real encoded frame reached WebRTC.
      const bool produced_bitstream = encoded_frames_ > encoded_before_gpu_attempt;
      if (!gpu_only_capture && produced_bitstream) {
        webrtc::EnableDxgiGpuOnlyCapture(true);
        std::fprintf(stderr,
                     "[LazyPC-GPU] zero-readback capture enabled after first encoded bitstream\n");
        std::fflush(stderr);
      }
      return kVideoCodecOk;
    }

    if (gpu_only_capture && !have_gpu_frame) {
      // Capture and encoding run on different threads, so the GPU-frame queue
      // can be briefly empty. In zero-readback mode the WebRTC frame is only a
      // placeholder; drop it but do not disable GPU-only capture on a queue miss.
      // Otherwise transient timing gaps cause repeated GPU/CPU mode oscillation.
      return kVideoCodecOk;
    }

    if (gpu_only_capture) {
      std::fprintf(stderr,
                   "[LazyPC-VIDEO-DIAG] GPU encode failed with a GPU frame present; encoded=%llu\n",
                   static_cast<unsigned long long>(encoded_frames_));
      std::fflush(stderr);
      // A GPU frame existed but GPU encoding failed. Restore CPU readback so
      // subsequent frames can use the CPU fallback rather than a placeholder.
      webrtc::EnableDxgiGpuOnlyCapture(false);
      std::fprintf(stderr,
                   "[LazyPC-GPU] GPU encode failed for available GPU frame; zero-readback capture disabled, resuming CPU fallback\n");
      std::fflush(stderr);
      return kVideoCodecOk;
    }

    // CPU fallback remains unchanged: WebRTC's I420 frame is converted into
    // NVENC's system-memory NV12 input buffer with libyuv.
    const auto buffer = frame.video_frame_buffer()->ToI420();
    if (!buffer || buffer->width() != static_cast<int>(width_) ||
        buffer->height() != static_cast<int>(height_)) {
      return kVideoCodecErrParameter;
    }
    NV_ENC_LOCK_INPUT_BUFFER lock_input{};
    lock_input.version = NV_ENC_LOCK_INPUT_BUFFER_VER;
    lock_input.inputBuffer = input_buffer_;
    if (api_.nvEncLockInputBuffer(encoder_, &lock_input) != NV_ENC_SUCCESS) {
      return kVideoCodecError;
    }
    auto* y = static_cast<uint8_t*>(lock_input.bufferDataPtr);
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wunsafe-buffer-usage"
    auto* uv = y + static_cast<size_t>(lock_input.pitch) * height_;
#pragma clang diagnostic pop
    const int convert_result = libyuv::I420ToNV12(
        buffer->DataY(), buffer->StrideY(), buffer->DataU(), buffer->StrideU(),
        buffer->DataV(), buffer->StrideV(), y, static_cast<int>(lock_input.pitch),
        uv, static_cast<int>(lock_input.pitch), static_cast<int>(width_),
        static_cast<int>(height_));
    const NVENCSTATUS unlock_status =
        api_.nvEncUnlockInputBuffer(encoder_, input_buffer_);
    if (convert_result != 0 || unlock_status != NV_ENC_SUCCESS) {
      return kVideoCodecError;
    }
    return SubmitInputLocked(input_buffer_, frame, frame_types);
  }

  void SetRates(const RateControlParameters& parameters) override {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!initialized_ || !encoder_) return;
    const uint32_t new_bitrate = static_cast<uint32_t>(std::max<int64_t>(
        300000, parameters.bitrate.get_sum_bps()));
    const uint32_t new_fps = static_cast<uint32_t>(
        std::max(1.0, parameters.framerate_fps));
    if (new_bitrate == bitrate_bps_ && new_fps == fps_) return;
    bitrate_bps_ = new_bitrate;
    fps_ = new_fps;
    config_.rcParams.averageBitRate = bitrate_bps_;
    config_.rcParams.maxBitRate = bitrate_bps_;
    config_.rcParams.vbvBufferSize = std::max<uint32_t>(1, bitrate_bps_ / fps_);
    config_.rcParams.vbvInitialDelay = config_.rcParams.vbvBufferSize;
    NV_ENC_RECONFIGURE_PARAMS reconfigure{};
    reconfigure.version = NV_ENC_RECONFIGURE_PARAMS_VER;
    reconfigure.reInitEncodeParams = init_params_;
    reconfigure.reInitEncodeParams.frameRateNum = fps_;
    reconfigure.reInitEncodeParams.encodeConfig = &config_;
    // Rate-only changes must not reset the NVENC session. Resetting the
    // encoder while WebRTC continuously submits frames can interrupt the
    // stream; keep the session alive and reconfigure bitrate/framerate only.
    reconfigure.resetEncoder = 0;
    reconfigure.forceIDR = 0;
    const NVENCSTATUS reconfigure_status =
        api_.nvEncReconfigureEncoder(encoder_, &reconfigure);
    if (reconfigure_status == NV_ENC_SUCCESS) {
      init_params_ = reconfigure.reInitEncodeParams;
    }
  }

  EncoderInfo GetEncoderInfo() const override {
    EncoderInfo info;
    info.implementation_name = "LazyPC-NVENC-H264";
    info.is_hardware_accelerated = true;
    info.supports_native_handle = false;
    info.has_trusted_rate_controller = true;
    return info;
  }

 private:
  struct GpuRegisteredResource {
    ID3D11Texture2D* texture = nullptr;  // Owned by D3D11VideoProcessor.
    NV_ENC_REGISTERED_PTR registered = nullptr;
  };

  bool EncodeGpuFrameLocked(const webrtc::DxgiGpuFrame& gpu_frame,
                            const webrtc::VideoFrame& frame,
                            const std::vector<webrtc::VideoFrameType>* frame_types) {
    if (!gpu_frame.texture || !gpu_frame.device ||
        gpu_frame.device.Get() != d3d_device_.Get()) {
      if (!gpu_path_logged_) {
        std::fprintf(stderr,
                     "[LazyPC-GPU] GPU frame device does not match NVENC session device; using CPU fallback\n");
        std::fflush(stderr);
        gpu_path_logged_ = true;
      }
      return false;
    }
    if (gpu_frame.format != DXGI_FORMAT_B8G8R8A8_UNORM &&
        gpu_frame.format != DXGI_FORMAT_B8G8R8A8_UNORM_SRGB) {
      return false;
    }

    // Serialize every use of the shared immediate context/driver with the DXGI
    // capture thread for the whole GPU sequence (released before the WebRTC
    // callback in SubmitInputLocked, re-taken for Unmap).
    D3dDeviceLock device_lock(d3d_multithread_.Get());

    if (!video_processor_ || vp_input_width_ != gpu_frame.width ||
        vp_input_height_ != gpu_frame.height) {
      for (auto& resource : gpu_registered_resources_) {
        if (resource.registered && encoder_) {
          api_.nvEncUnregisterResource(encoder_, resource.registered);
        }
      }
      gpu_registered_resources_.clear();
      if (video_processor_) video_processor_->Release();
      video_processor_ = std::make_unique<lazypc::D3D11VideoProcessor>();
      if (!video_processor_->Initialize(d3d_device_.Get(), d3d_context_.Get(),
                                        gpu_frame.width, gpu_frame.height,
                                        width_, height_)) {
        video_processor_.reset();
        return false;
      }
      vp_input_width_ = gpu_frame.width;
      vp_input_height_ = gpu_frame.height;
    }

    Microsoft::WRL::ComPtr<ID3D11Texture2D> nv12_texture;
    RECT crop{0, 0, static_cast<LONG>(gpu_frame.width),
              static_cast<LONG>(gpu_frame.height)};
    if (!video_processor_->Process(gpu_frame.texture.Get(), &crop,
                                   nv12_texture.GetAddressOf())) {
      std::fprintf(stderr, "[LazyPC-GPU] VideoProcessor Process failed\n");
      std::fflush(stderr);
      return false;
    }

    // Keep a persistent NVENC registration for each rotating D3D11 surface.
    auto resource_it = std::find_if(
        gpu_registered_resources_.begin(), gpu_registered_resources_.end(),
        [&nv12_texture](const GpuRegisteredResource& resource) {
          return resource.texture == nv12_texture.Get();
        });
    if (resource_it == gpu_registered_resources_.end()) {
      NV_ENC_REGISTER_RESOURCE reg{};
      reg.version = NV_ENC_REGISTER_RESOURCE_VER;
      reg.resourceType = NV_ENC_INPUT_RESOURCE_TYPE_DIRECTX;
      reg.resourceToRegister = nv12_texture.Get();
      reg.width = width_;
      reg.height = height_;
      reg.pitch = 0;
      reg.bufferFormat = NV_ENC_BUFFER_FORMAT_NV12;
      reg.subResourceIndex = 0;
      const NVENCSTATUS status = api_.nvEncRegisterResource(encoder_, &reg);
      if (status != NV_ENC_SUCCESS) {
        std::fprintf(stderr,
                     "[LazyPC-GPU] nvEncRegisterResource failed status=%d\n",
                     static_cast<int>(status));
        std::fflush(stderr);
        return false;
      }
      gpu_registered_resources_.push_back(
          GpuRegisteredResource{nv12_texture.Get(), reg.registeredResource});
      resource_it = std::prev(gpu_registered_resources_.end());
    }

    NV_ENC_MAP_INPUT_RESOURCE map{};
    map.version = NV_ENC_MAP_INPUT_RESOURCE_VER;
    map.registeredResource = resource_it->registered;
    const NVENCSTATUS map_status = api_.nvEncMapInputResource(encoder_, &map);
    if (map_status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-GPU] nvEncMapInputResource failed status=%d\n",
                   static_cast<int>(map_status));
      std::fflush(stderr);
      return false;
    }

    if (!gpu_path_logged_) {
      std::fprintf(stderr,
                   "[LazyPC-GPU] GPU path active: DXGI BGRA -> D3D11 VideoProcessor NV12 -> NVENC texture input\n");
      std::fflush(stderr);
      gpu_path_logged_ = true;
    }
    const int32_t result =
        SubmitInputLocked(map.mappedResource, frame, frame_types, &device_lock);
    const NVENCSTATUS unmap_status =
        api_.nvEncUnmapInputResource(encoder_, map.mappedResource);
    if (unmap_status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-GPU] nvEncUnmapInputResource failed status=%d\n",
                   static_cast<int>(unmap_status));
      std::fflush(stderr);
    }
    return result == kVideoCodecOk;
  }

  int32_t SubmitInputLocked(NV_ENC_INPUT_PTR input,
                            const webrtc::VideoFrame& frame,
                            const std::vector<webrtc::VideoFrameType>* frame_types,
                            D3dDeviceLock* device_lock = nullptr) {
    NV_ENC_PIC_PARAMS pic{};
    pic.version = NV_ENC_PIC_PARAMS_VER;
    pic.inputBuffer = input;
    pic.bufferFmt = NV_ENC_BUFFER_FORMAT_NV12;
    pic.inputWidth = width_;
    pic.inputHeight = height_;
    pic.outputBitstream = bitstream_buffer_;
    pic.pictureStruct = NV_ENC_PIC_STRUCT_FRAME;
    pic.inputTimeStamp = frame.timestamp_us();
    bool force_keyframe = false;
    if (frame_types && !frame_types->empty()) {
      force_keyframe = (*frame_types)[0] == webrtc::VideoFrameType::kVideoFrameKey;
    }
    if (force_keyframe) {
      pic.encodePicFlags |= NV_ENC_PIC_FLAG_FORCEIDR | NV_ENC_PIC_FLAG_OUTPUT_SPSPPS;
    }
    const NVENCSTATUS encode_status = api_.nvEncEncodePicture(encoder_, &pic);
    if (encode_status != NV_ENC_SUCCESS && encode_status != NV_ENC_ERR_NEED_MORE_INPUT) {
      std::fprintf(stderr,
                   "[LazyPC-GPU-DIAG] nvEncEncodePicture failed status=%d encoded=%llu\n",
                   static_cast<int>(encode_status),
                   static_cast<unsigned long long>(encoded_frames_));
      std::fflush(stderr);
      return kVideoCodecError;
    }
    if (encode_status == NV_ENC_ERR_NEED_MORE_INPUT) {
      if (encoded_frames_ < 5 || (encoded_frames_ % 120) == 0) {
        std::fprintf(stderr,
                     "[LazyPC-GPU-DIAG] nvEncEncodePicture NEED_MORE_INPUT encoded=%llu\n",
                     static_cast<unsigned long long>(encoded_frames_));
        std::fflush(stderr);
      }
      return kVideoCodecOk;
    }

    NV_ENC_LOCK_BITSTREAM lock_bits{};
    lock_bits.version = NV_ENC_LOCK_BITSTREAM_VER;
    lock_bits.outputBitstream = bitstream_buffer_;
    lock_bits.doNotWait = 0;
    const NVENCSTATUS lock_status = api_.nvEncLockBitstream(encoder_, &lock_bits);
    if (lock_status != NV_ENC_SUCCESS) {
      std::fprintf(stderr,
                   "[LazyPC-GPU-DIAG] nvEncLockBitstream failed status=%d encoded=%llu\n",
                   static_cast<int>(lock_status),
                   static_cast<unsigned long long>(encoded_frames_));
      std::fflush(stderr);
      return kVideoCodecError;
    }

    const size_t bytes = lock_bits.bitstreamSizeInBytes;
    auto encoded_buffer = webrtc::EncodedImageBuffer::Create(bytes);
    if (encoded_buffer && bytes > 0) {
      std::memcpy(encoded_buffer->data(), lock_bits.bitstreamBufferPtr, bytes);
    }
    const NVENCSTATUS unlock_bits_status =
        api_.nvEncUnlockBitstream(encoder_, bitstream_buffer_);
    if (!encoded_buffer || bytes == 0 || unlock_bits_status != NV_ENC_SUCCESS) {
      return kVideoCodecError;
    }

    webrtc::EncodedImage encoded;
    encoded.SetEncodedData(encoded_buffer);
    encoded._encodedWidth = static_cast<int>(width_);
    encoded._encodedHeight = static_cast<int>(height_);
    encoded.SetRtpTimestamp(frame.rtp_timestamp());
    encoded.SetFrameType((lock_bits.pictureType == NV_ENC_PIC_TYPE_IDR || force_keyframe)
                             ? webrtc::VideoFrameType::kVideoFrameKey
                             : webrtc::VideoFrameType::kVideoFrameDelta);
    webrtc::CodecSpecificInfo codec_specific_info{};
    codec_specific_info.codecType = webrtc::kVideoCodecH264;
    // Never call into WebRTC (packetizer/pacer locks) while holding the D3D
    // device lock: that would create a lock-order inversion with the capture thread.
    if (device_lock) device_lock->Unlock();
    const auto callback_result = callback_->OnEncodedImage(encoded, &codec_specific_info);
    if (device_lock) device_lock->Lock();
    if (callback_result.error != webrtc::EncodedImageCallback::Result::OK) {
      std::fprintf(stderr, "[LazyPC-VIDEO] OnEncodedImage reported error=%d\n",
                   static_cast<int>(callback_result.error));
      std::fflush(stderr);
    }
    ++encoded_frames_;
    if (encoded_frames_ == 1) {
      std::fprintf(stderr,
                   "[LazyPC-VIDEO] NVENC ENCODED first frame size=%ux%u bytes=%zu\n",
                   width_, height_, bytes);
      std::fflush(stderr);
    }
    return kVideoCodecOk;
  }

  void CloseEncoderSessionLocked() {
    D3dDeviceLock device_lock(d3d_multithread_.Get());
    for (auto& resource : gpu_registered_resources_) {
      if (resource.registered && encoder_) {
        api_.nvEncUnregisterResource(encoder_, resource.registered);
      }
    }
    gpu_registered_resources_.clear();
    if (video_processor_) video_processor_->Release();
    video_processor_.reset();
    vp_input_width_ = vp_input_height_ = 0;
    if (encoder_) {
      if (bitstream_buffer_) api_.nvEncDestroyBitstreamBuffer(encoder_, bitstream_buffer_);
      if (input_buffer_) api_.nvEncDestroyInputBuffer(encoder_, input_buffer_);
      api_.nvEncDestroyEncoder(encoder_);
    }
    encoder_ = nullptr;
    input_buffer_ = nullptr;
    bitstream_buffer_ = nullptr;
  }

  bool LoadApiLocked() {
    if (nvenc_module_) return true;
    nvenc_module_ = LoadLibraryW(L"nvEncodeAPI64.dll");
    if (!nvenc_module_) return false;
    using GetMaxVersionFn = NVENCSTATUS(NVENCAPI*)(uint32_t*);
    auto get_max_version = reinterpret_cast<GetMaxVersionFn>(
        GetProcAddress(nvenc_module_, "NvEncodeAPIGetMaxSupportedVersion"));
    using CreateInstanceFn = NVENCSTATUS(NVENCAPI*)(NV_ENCODE_API_FUNCTION_LIST*);
    auto create_instance = reinterpret_cast<CreateInstanceFn>(
        GetProcAddress(nvenc_module_, "NvEncodeAPICreateInstance"));
    if (!create_instance || !get_max_version) {
      std::fprintf(stderr, "[LazyPC-VIDEO] NVENC API missing required entry point(s)\n");
      std::fflush(stderr);
      return false;
    }

    uint32_t driver_max_version = 0;
    NVENCSTATUS version_status = get_max_version(&driver_max_version);
    const uint32_t header_version =
        (NVENCAPI_MAJOR_VERSION << 4) | NVENCAPI_MINOR_VERSION;
    if (version_status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-VIDEO] NVENC GetMaxSupportedVersion failed status=%d\n",
                   static_cast<int>(version_status));
      std::fflush(stderr);
      return false;
    }
    std::fprintf(stderr, "[LazyPC-VIDEO] NVENC API versions: headers=%u.%u driver_max=%u.%u\n",
                 NVENCAPI_MAJOR_VERSION, NVENCAPI_MINOR_VERSION,
                 driver_max_version >> 4, driver_max_version & 0xF);
    std::fflush(stderr);
    if (header_version > driver_max_version) {
      std::fprintf(stderr,
                   "[LazyPC-VIDEO] NVENC API mismatch: installed NVIDIA driver is too old for these headers; update the NVIDIA driver or build against a matching NVENC SDK\n");
      std::fflush(stderr);
      return false;
    }

    api_ = {};
    api_.version = NV_ENCODE_API_FUNCTION_LIST_VER;
    NVENCSTATUS create_status = create_instance(&api_);
    if (create_status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-VIDEO] NVENC CreateInstance failed status=%d\n",
                   static_cast<int>(create_status));
      std::fflush(stderr);
      return false;
    }
    return true;
  }

  bool CreateD3DDeviceLocked() {
    ComPtr<IDXGIFactory1> factory;
    if (FAILED(CreateDXGIFactory1(IID_PPV_ARGS(&factory)))) return false;
    ComPtr<IDXGIAdapter1> selected;
    for (UINT i = 0;; ++i) {
      ComPtr<IDXGIAdapter1> adapter;
      if (factory->EnumAdapters1(i, &adapter) == DXGI_ERROR_NOT_FOUND) break;
      DXGI_ADAPTER_DESC1 desc{};
      if (SUCCEEDED(adapter->GetDesc1(&desc)) && desc.VendorId == 0x10DE) {
        selected = adapter;
        break;
      }
    }
    if (!selected) return false;
    D3D_FEATURE_LEVEL feature_level{};
    const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
    HRESULT hr = D3D11CreateDevice(selected.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr,
                                   D3D11_CREATE_DEVICE_VIDEO_SUPPORT, levels,
                                   static_cast<UINT>(std::size(levels)), D3D11_SDK_VERSION,
                                   &d3d_device_, &feature_level, &d3d_context_);
    if (hr == E_INVALIDARG) {
      hr = D3D11CreateDevice(selected.Get(), D3D_DRIVER_TYPE_UNKNOWN, nullptr,
                             D3D11_CREATE_DEVICE_VIDEO_SUPPORT, GetFeatureLevelsAfterFirst(levels), 1,
                             D3D11_SDK_VERSION, &d3d_device_, &feature_level,
                             &d3d_context_);
    }
    return SUCCEEDED(hr);
  }

  bool OpenEncoderOnDeviceLocked(ID3D11Device* device) {
    if (!device) return false;
    if (encoder_) return d3d_device_.Get() == device;
    d3d_device_ = device;
    d3d_device_->GetImmediateContext(&d3d_context_);
    // The DXGI capturer and the video processor may use this immediate context
    // from different threads. Enable D3D11's context serialization.
    d3d_multithread_.Reset();
    if (SUCCEEDED(d3d_device_.As(&d3d_multithread_)) && d3d_multithread_) {
      d3d_multithread_->SetMultithreadProtected(TRUE);
    }
    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS open{};
    open.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
    open.device = d3d_device_.Get();
    open.deviceType = NV_ENC_DEVICE_TYPE_DIRECTX;
    open.apiVersion = NVENCAPI_VERSION;
    NVENCSTATUS status = api_.nvEncOpenEncodeSessionEx(&open, &encoder_);
    if (status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-VIDEO] NVENC step=OpenEncodeSessionEx status=%d\n",
                   static_cast<int>(status));
      std::fflush(stderr);
      return false;
    }

    NV_ENC_PRESET_CONFIG preset{};
    preset.version = NV_ENC_PRESET_CONFIG_VER;
    preset.presetCfg.version = NV_ENC_CONFIG_VER;
    status = api_.nvEncGetEncodePresetConfigEx(
        encoder_, NV_ENC_CODEC_H264_GUID, NV_ENC_PRESET_P2_GUID,
        NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY, &preset);
    if (status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-VIDEO] NVENC step=GetEncodePresetConfigEx status=%d\n",
                   static_cast<int>(status));
      std::fflush(stderr);
      return false;
    }

    config_ = preset.presetCfg;
    config_.gopLength = NVENC_INFINITE_GOPLENGTH;
    config_.frameIntervalP = 1;
    config_.rcParams.rateControlMode = NV_ENC_PARAMS_RC_CBR;
    config_.rcParams.averageBitRate = bitrate_bps_;
    config_.rcParams.maxBitRate = bitrate_bps_;
    config_.rcParams.vbvBufferSize = std::max<uint32_t>(1, bitrate_bps_ / fps_);
    config_.rcParams.vbvInitialDelay = config_.rcParams.vbvBufferSize;
    config_.rcParams.enableLookahead = 0;
    config_.encodeCodecConfig.h264Config.repeatSPSPPS = 1;
    config_.encodeCodecConfig.h264Config.idrPeriod = NVENC_INFINITE_GOPLENGTH;

    init_params_ = {};
    init_params_.version = NV_ENC_INITIALIZE_PARAMS_VER;
    init_params_.encodeGUID = NV_ENC_CODEC_H264_GUID;
    init_params_.presetGUID = NV_ENC_PRESET_P2_GUID;
    init_params_.tuningInfo = NV_ENC_TUNING_INFO_ULTRA_LOW_LATENCY;
    init_params_.encodeWidth = width_;
    init_params_.encodeHeight = height_;
    init_params_.darWidth = width_;
    init_params_.darHeight = height_;
    init_params_.frameRateNum = fps_;
    init_params_.frameRateDen = 1;
    init_params_.enablePTD = 1;
    init_params_.encodeConfig = &config_;
    status = api_.nvEncInitializeEncoder(encoder_, &init_params_);
    if (status != NV_ENC_SUCCESS) {
      std::fprintf(stderr,
                   "[LazyPC-VIDEO] NVENC step=InitializeEncoder status=%d size=%ux%u fps=%u bitrate=%u\n",
                   static_cast<int>(status), width_, height_, fps_, bitrate_bps_);
      std::fflush(stderr);
      return false;
    }

    NV_ENC_CREATE_INPUT_BUFFER input{};
    input.version = NV_ENC_CREATE_INPUT_BUFFER_VER;
    input.width = width_;
    input.height = height_;
    input.memoryHeap = NV_ENC_MEMORY_HEAP_SYSMEM_CACHED;
    input.bufferFmt = NV_ENC_BUFFER_FORMAT_NV12;
    status = api_.nvEncCreateInputBuffer(encoder_, &input);
    if (status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-VIDEO] NVENC step=CreateInputBuffer status=%d\n",
                   static_cast<int>(status));
      std::fflush(stderr);
      return false;
    }
    input_buffer_ = input.inputBuffer;

    NV_ENC_CREATE_BITSTREAM_BUFFER output{};
    output.version = NV_ENC_CREATE_BITSTREAM_BUFFER_VER;
    output.memoryHeap = NV_ENC_MEMORY_HEAP_SYSMEM_CACHED;
    status = api_.nvEncCreateBitstreamBuffer(encoder_, &output);
    if (status != NV_ENC_SUCCESS) {
      std::fprintf(stderr, "[LazyPC-VIDEO] NVENC step=CreateBitstreamBuffer status=%d\n",
                   static_cast<int>(status));
      std::fflush(stderr);
      return false;
    }
    bitstream_buffer_ = output.bitstreamBuffer;
    return true;
  }

  void ReleaseLocked() {
    initialized_ = false;
    webrtc::EnableDxgiGpuFrameQueue(false);
    webrtc::EnableDxgiGpuOnlyCapture(false);
    CloseEncoderSessionLocked();
    d3d_context_.Reset();
    d3d_multithread_.Reset();
    d3d_device_.Reset();
    gpu_init_wait_frames_ = 0;
    gpu_path_logged_ = false;
    last_gpu_frame_ = webrtc::DxgiGpuFrame{};
    have_last_gpu_frame_ = false;
    if (nvenc_module_) {
      FreeLibrary(nvenc_module_);
      nvenc_module_ = nullptr;
    }
    api_ = {};
  }

  mutable std::mutex mutex_;
  webrtc::EncodedImageCallback* callback_ = nullptr;
  bool initialized_ = false;
  uint64_t encoded_frames_ = 0;
  uint32_t width_ = 0, height_ = 0, fps_ = 30, bitrate_bps_ = 6000000;
  HMODULE nvenc_module_ = nullptr;
  NV_ENCODE_API_FUNCTION_LIST api_{};
  void* encoder_ = nullptr;
  NV_ENC_INPUT_PTR input_buffer_ = nullptr;
  NV_ENC_OUTPUT_PTR bitstream_buffer_ = nullptr;
  NV_ENC_CONFIG config_{};
  NV_ENC_INITIALIZE_PARAMS init_params_{};
  ComPtr<ID3D11Device> d3d_device_;
  ComPtr<ID3D11DeviceContext> d3d_context_;
  ComPtr<ID3D10Multithread> d3d_multithread_;
  std::unique_ptr<lazypc::D3D11VideoProcessor> video_processor_;
  std::vector<GpuRegisteredResource> gpu_registered_resources_;
  uint32_t vp_input_width_ = 0;
  uint32_t vp_input_height_ = 0;
  uint32_t gpu_init_wait_frames_ = 0;
  bool gpu_path_logged_ = false;
  webrtc::DxgiGpuFrame last_gpu_frame_;
  bool have_last_gpu_frame_ = false;
};
#else
class NvencEncoder final : public webrtc::VideoEncoder {
 public:
  int32_t InitEncode(const webrtc::VideoCodec*, const Settings&) override { return kVideoCodecError; }
  int32_t RegisterEncodeCompleteCallback(webrtc::EncodedImageCallback*) override { return kVideoCodecError; }
  int32_t Release() override { return kVideoCodecOk; }
  int32_t Encode(const webrtc::VideoFrame&, const std::vector<webrtc::VideoFrameType>*) override { return kVideoCodecError; }
};
#endif

class LazyPcEncoderFactory final : public webrtc::VideoEncoderFactory {
 public:
  explicit LazyPcEncoderFactory(std::unique_ptr<webrtc::VideoEncoderFactory> fallback)
      : fallback_(std::move(fallback)) {}

  std::vector<webrtc::SdpVideoFormat> GetSupportedFormats() const override {
    // This native sender is intentionally H.264-only: if VP8/VP9/AV1 are
    // advertised here, WebRTC may still instantiate one of those encoders
    // despite the transceiver preference order. Keep every H.264 profile
    // supported by the builtin factory, but do not advertise other codecs.
    std::vector<webrtc::SdpVideoFormat> formats;
    if (!fallback_) return formats;

    for (const auto& format : fallback_->GetSupportedFormats()) {
      if (format.name == "H264") {
        formats.push_back(format);
      }
    }
    return formats;
  }

  std::unique_ptr<webrtc::VideoEncoder> Create(
      const webrtc::Environment& env,
      const webrtc::SdpVideoFormat& format) override {
    if (format.name == "H264") {
      std::fprintf(stderr, "[LazyPC-VIDEO] Encoder selected: H264 -> NVIDIA NVENC\n");
      std::fflush(stderr);
      return std::make_unique<NvencEncoder>();
    }
    std::fprintf(stderr, "[LazyPC-VIDEO] Encoder selected: %s -> WebRTC builtin\n",
                 format.name.c_str());
    std::fflush(stderr);
    return fallback_ ? fallback_->Create(env, format) : nullptr;
  }

 private:
  std::unique_ptr<webrtc::VideoEncoderFactory> fallback_;
};

}  // namespace

std::unique_ptr<webrtc::VideoEncoderFactory> CreateLazyPcVideoEncoderFactory(
    std::unique_ptr<webrtc::VideoEncoderFactory> fallback) {
  std::fprintf(stderr,
               "[LazyPC-VIDEO] Encoder policy: H264-only; non-H264 encoders disabled to force NVENC path\n");
  std::fflush(stderr);
  return std::make_unique<LazyPcEncoderFactory>(std::move(fallback));
}