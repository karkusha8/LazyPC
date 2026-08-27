from __future__ import annotations

from typing import Any

import av
from aiortc.codecs import get_encoder as _original_get_encoder

from core.webrtc.h264_cpu import H264CPUEncoder
from core.webrtc.h264_nvenc import H264NVENCEncoder
from core.webrtc.opus_audio import OpusAudioEncoder


def _try_nvenc() -> bool:
    """
    Check that NVENC is not only listed by PyAV, but can actually open.

    We use a small temporary encoder context. This is done once when the
    encoder backend is selected, not for every video frame.
    """
    if "h264_nvenc" not in av.codecs_available:
        print("[LazyPC][ENCODER] NVENC not present -> CPU")
        return False

    try:
        codec = av.CodecContext.create("h264_nvenc", "w")
        codec.width = 1280
        codec.height = 720
        codec.pix_fmt = "yuv420p"
        codec.open()

        try:
            codec.close()
        except Exception:
            pass

        print("[LazyPC][ENCODER] NVENC available -> GPU")
        return True

    except Exception as exc:
        print(
            "[LazyPC][ENCODER] NVENC unavailable -> CPU "
            f"({type(exc).__name__}: {exc})"
        )
        return False


_NVENC_AVAILABLE = _try_nvenc()


def get_encoder(codec: Any):
    """
    LazyPC aiortc encoder factory.

    H264:
        NVENC -> GPU
        CPU   -> fallback

    Opus:
        LazyPC custom audio encoder

    Everything else:
        aiortc default encoder
    """

    mime_type = getattr(codec, "mimeType", "").lower()

    if mime_type == "video/h264":
        if _NVENC_AVAILABLE:
            print(
                "[LazyPC] get_encoder -> NVENC H264Encoder"
            )
            return H264NVENCEncoder()

        print(
            "[LazyPC] get_encoder -> CPU H264Encoder"
        )
        return H264CPUEncoder()

    if mime_type == "audio/opus":
        print(
            "[LazyPC] get_encoder -> LazyPC OpusAudioEncoder"
        )
        return OpusAudioEncoder()

    return _original_get_encoder(codec)
