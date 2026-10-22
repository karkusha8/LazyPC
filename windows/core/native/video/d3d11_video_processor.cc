#include "d3d11_video_processor.h"

#ifdef _WIN32

namespace lazypc {
namespace {

bool ValidRect(const RECT& r, uint32_t width, uint32_t height) {
  return r.left >= 0 && r.top >= 0 && r.right > r.left && r.bottom > r.top &&
         static_cast<uint32_t>(r.right) <= width &&
         static_cast<uint32_t>(r.bottom) <= height;
}

}  // namespace

D3D11VideoProcessor::~D3D11VideoProcessor() { Release(); }

bool D3D11VideoProcessor::Initialize(ID3D11Device* device,
                                     ID3D11DeviceContext* context,
                                     uint32_t input_width,
                                     uint32_t input_height,
                                     uint32_t output_width,
                                     uint32_t output_height) {
  Release();
  if (!device || !context || input_width < 2 || input_height < 2 ||
      output_width < 2 || output_height < 2 || (output_width & 1U) ||
      (output_height & 1U)) {
    return false;
  }

  device_ = device;
  context_ = context;
  input_width_ = input_width;
  input_height_ = input_height;
  output_width_ = output_width;
  output_height_ = output_height;

  if (FAILED(device_.As(&video_device_)) ||
      FAILED(context_.As(&video_context_))) {
    Release();
    return false;
  }

  D3D11_VIDEO_PROCESSOR_CONTENT_DESC desc{};
  desc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
  desc.InputFrameRate = {60, 1};
  desc.InputWidth = input_width_;
  desc.InputHeight = input_height_;
  desc.OutputFrameRate = {60, 1};
  desc.OutputWidth = output_width_;
  desc.OutputHeight = output_height_;
  desc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

  if (FAILED(video_device_->CreateVideoProcessorEnumerator(&desc, &enumerator_)) ||
      FAILED(video_device_->CreateVideoProcessor(enumerator_.Get(), 0, &processor_))) {
    Release();
    return false;
  }

  D3D11_TEXTURE2D_DESC texture_desc{};
  texture_desc.Width = output_width_;
  texture_desc.Height = output_height_;
  texture_desc.MipLevels = 1;
  texture_desc.ArraySize = 1;
  texture_desc.Format = DXGI_FORMAT_NV12;
  texture_desc.SampleDesc.Count = 1;
  texture_desc.Usage = D3D11_USAGE_DEFAULT;
  texture_desc.BindFlags = D3D11_BIND_RENDER_TARGET;
  for (auto& output_texture : output_textures_) {
    if (FAILED(device_->CreateTexture2D(&texture_desc, nullptr, &output_texture))) {
      Release();
      return false;
    }
  }
  next_output_texture_ = 0;
  return true;
}

bool D3D11VideoProcessor::Process(ID3D11Texture2D* input,
                                  const RECT* crop_rect,
                                  ID3D11Texture2D** output_texture) {
  if (output_texture) *output_texture = nullptr;
  if (!input || !output_texture || !device_ || !video_device_ ||
      !video_context_ || !enumerator_ || !processor_ || !output_texture_) {
    return false;
  }

  Microsoft::WRL::ComPtr<ID3D11Device> input_device;
  input->GetDevice(&input_device);
  if (input_device.Get() != device_.Get()) return false;

  D3D11_TEXTURE2D_DESC input_desc{};
  input->GetDesc(&input_desc);
  if (input_desc.Width != input_width_ || input_desc.Height != input_height_) {
    return false;
  }

  RECT source{0, 0, static_cast<LONG>(input_width_),
              static_cast<LONG>(input_height_)};
  if (crop_rect) source = *crop_rect;
  if (!ValidRect(source, input_width_, input_height_)) return false;

  Microsoft::WRL::ComPtr<ID3D11VideoProcessorInputView> input_view;
  D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC input_view_desc{};
  input_view_desc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
  input_view_desc.Texture2D.MipSlice = 0;
  input_view_desc.Texture2D.ArraySlice = 0;
  if (FAILED(video_device_->CreateVideoProcessorInputView(
          input, enumerator_.Get(), &input_view_desc, &input_view))) {
    return false;
  }

  auto& current_output_texture = output_textures_[next_output_texture_];
  Microsoft::WRL::ComPtr<ID3D11VideoProcessorOutputView> output_view;
  D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC output_view_desc{};
  output_view_desc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
  output_view_desc.Texture2D.MipSlice = 0;
  if (FAILED(video_device_->CreateVideoProcessorOutputView(
          current_output_texture.Get(), enumerator_.Get(), &output_view_desc,
          &output_view))) {
    return false;
  }

  RECT destination{0, 0, static_cast<LONG>(output_width_),
                   static_cast<LONG>(output_height_)};
  video_context_->VideoProcessorSetStreamFrameFormat(
      processor_.Get(), 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
  video_context_->VideoProcessorSetStreamSourceRect(
      processor_.Get(), 0, TRUE, &source);
  video_context_->VideoProcessorSetStreamDestRect(
      processor_.Get(), 0, TRUE, &destination);
  video_context_->VideoProcessorSetOutputTargetRect(
      processor_.Get(), TRUE, &destination);

  D3D11_VIDEO_PROCESSOR_STREAM stream{};
  stream.Enable = TRUE;
  stream.pInputSurface = input_view.Get();
  if (FAILED(video_context_->VideoProcessorBlt(
          processor_.Get(), output_view.Get(), 0, 1, &stream))) {
    return false;
  }

  *output_texture = current_output_texture.Get();
  (*output_texture)->AddRef();
  next_output_texture_ = (next_output_texture_ + 1) % output_textures_.size();
  return true;
}

void D3D11VideoProcessor::Release() {
  for (auto& output_texture : output_textures_) output_texture.Reset();
  next_output_texture_ = 0;
  processor_.Reset();
  enumerator_.Reset();
  video_context_.Reset();
  video_device_.Reset();
  context_.Reset();
  device_.Reset();
  input_width_ = input_height_ = output_width_ = output_height_ = 0;
}

}  // namespace lazypc

#endif  // _WIN32
