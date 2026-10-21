#pragma once

#ifdef _WIN32

#include <cstdint>
#include <d3d11.h>
#include <d3d11_1.h>
#include <wrl/client.h>
#include <windows.h>

namespace lazypc {

class D3D11VideoProcessor final {
 public:
  D3D11VideoProcessor() = default;
  ~D3D11VideoProcessor();

  D3D11VideoProcessor(const D3D11VideoProcessor&) = delete;
  D3D11VideoProcessor& operator=(const D3D11VideoProcessor&) = delete;

  bool Initialize(ID3D11Device* device,
                  ID3D11DeviceContext* context,
                  uint32_t input_width,
                  uint32_t input_height,
                  uint32_t output_width,
                  uint32_t output_height);

  bool Process(ID3D11Texture2D* input,
               const RECT* crop_rect,
               ID3D11Texture2D** output_texture);

  void Release();

 private:
  Microsoft::WRL::ComPtr<ID3D11Device> device_;
  Microsoft::WRL::ComPtr<ID3D11DeviceContext> context_;
  Microsoft::WRL::ComPtr<ID3D11VideoDevice> video_device_;
  Microsoft::WRL::ComPtr<ID3D11VideoContext> video_context_;
  Microsoft::WRL::ComPtr<ID3D11VideoProcessorEnumerator> enumerator_;
  Microsoft::WRL::ComPtr<ID3D11VideoProcessor> processor_;
  Microsoft::WRL::ComPtr<ID3D11Texture2D> output_texture_;
  uint32_t input_width_ = 0;
  uint32_t input_height_ = 0;
  uint32_t output_width_ = 0;
  uint32_t output_height_ = 0;
};

}  // namespace lazypc

#endif  // _WIN32