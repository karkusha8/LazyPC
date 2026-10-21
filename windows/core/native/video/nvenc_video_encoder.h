#pragma once

#include <memory>
#include <mutex>
#include <vector>

#include "api/video_codecs/video_encoder.h"
#include "api/video_codecs/video_encoder_factory.h"

namespace webrtc {
class VideoEncoderFactory;
}

// Wraps WebRTC's normal factory, replacing only H.264 with the LazyPC NVENC
// encoder. Other codecs continue to be provided by the stock factory.
std::unique_ptr<webrtc::VideoEncoderFactory> CreateLazyPcVideoEncoderFactory(
    std::unique_ptr<webrtc::VideoEncoderFactory> fallback);
