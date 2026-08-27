from __future__ import annotations

import fractions
from typing import Iterator

import av
from aiortc.codecs.h264 import H264Encoder as _AiortcH264Encoder


FPS = 60
BITRATE = 8_000_000


class H264CPUEncoder(_AiortcH264Encoder):
    """H.264 encoder using CPU/libx264."""

    def _encode_frame(
        self,
        frame: av.VideoFrame,
        force_keyframe: bool,
    ) -> Iterator[bytes]:
        if force_keyframe:
            frame.pict_type = av.video.frame.PictureType.I
        else:
            frame.pict_type = av.video.frame.PictureType.NONE

        if self.codec is None:
            if "libx264" not in av.codecs_available:
                raise RuntimeError(
                    "libx264 is not available in this PyAV/FFmpeg build"
                )

            print(
                "[LazyPC][CPU] creating encoder: "
                f"libx264 {frame.width}x{frame.height} "
                f"{FPS} FPS {BITRATE / 1_000_000:.1f} Mbps"
            )

            codec = av.CodecContext.create("libx264", "w")
            codec.width = frame.width
            codec.height = frame.height
            codec.bit_rate = BITRATE
            codec.pix_fmt = "yuv420p"
            codec.framerate = fractions.Fraction(FPS, 1)
            codec.time_base = fractions.Fraction(1, FPS)

            codec.options = {
                "level": "50",
                "preset": "faster",
                "profile": "high",
                "maxrate": str(BITRATE),
                "bufsize": str(BITRATE // 2),
                "g": str(FPS),
                "sc_threshold": "0",
                "bf": "0",
                "threads": "8",
                "slices": "1",
                "x264-params": (
                    "nal-hrd=cbr:"
                    "rc-lookahead=0:"
                    "sync-lookahead=0:"
                    "mbtree=1:"
                    "intra-refresh=1:"
                    "repeat-headers=1:"
                    "weightp=0"
                ),
            }

            codec.open()
            self.codec = codec

            print("[LazyPC][CPU] encoder created")

        try:
            data = b""
            for packet in self.codec.encode(frame):
                data += bytes(packet)

            if data:
                yield from self._split_bitstream(data)

        except Exception as exc:
            print(
                "[LazyPC][CPU] FRAME ENCODE ERROR: "
                f"{type(exc).__name__}: {exc}"
            )
            raise

    @staticmethod
    def _split_bitstream(data: bytes) -> Iterator[bytes]:
        """Split Annex-B H.264 into individual NAL units."""
        i = 0
        length = len(data)

        while True:
            pos3 = data.find(b"\x00\x00\x01", i)
            if pos3 < 0:
                return

            nal_start = pos3 + 3

            # The 3-byte marker can be the tail of a 4-byte marker.
            if pos3 > 0 and data[pos3 - 1] == 0:
                nal_start = pos3 + 3

            next_pos = data.find(b"\x00\x00\x01", nal_start)

            if next_pos < 0:
                nal = data[nal_start:length]
                if nal:
                    yield nal
                return

            nal_end = next_pos
            if next_pos > nal_start and data[next_pos - 1] == 0:
                nal_end -= 1

            nal = data[nal_start:nal_end]
            if nal:
                yield nal

            i = next_pos
