from __future__ import annotations

import fractions
from typing import Iterator

import av
from aiortc.codecs.h264 import H264Encoder as _AiortcH264Encoder


FPS = 60
BITRATE = 8_000_000


class H264NVENCEncoder(_AiortcH264Encoder):
    """H.264 encoder backed by NVIDIA NVENC."""

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
            if "h264_nvenc" not in av.codecs_available:
                raise RuntimeError(
                    "h264_nvenc is not available in this PyAV/FFmpeg build"
                )

            print(
                "[LazyPC][NVENC] creating encoder: "
                f"h264_nvenc {frame.width}x{frame.height} "
                f"{FPS} FPS {BITRATE / 1_000_000:.1f} Mbps"
            )

            codec = av.CodecContext.create("h264_nvenc", "w")
            codec.width = frame.width
            codec.height = frame.height
            codec.bit_rate = BITRATE
            codec.pix_fmt = "yuv420p"
            codec.framerate = fractions.Fraction(FPS, 1)
            codec.time_base = fractions.Fraction(1, FPS)

            # This is the configuration already proven on the current PC.
            codec.options = {
                "preset": "p1",
            }

            codec.open()
            self.codec = codec

            print("[LazyPC][NVENC] encoder created")

        try:
            for packet in self.codec.encode(frame):
                data = bytes(packet)
                if not data:
                    continue

                for nal in self._split_annex_b(data):
                    if nal:
                        yield nal

        except Exception as exc:
            print(
                "[LazyPC][NVENC] FRAME ENCODE ERROR: "
                f"{type(exc).__name__}: {exc}"
            )
            raise

    @staticmethod
    def _split_annex_b(data: bytes) -> list[bytes]:
        """Convert an Annex-B H.264 byte stream into NAL units."""
        nal_units: list[bytes] = []
        length = len(data)

        if not data:
            return nal_units

        starts: list[int] = []
        i = 0

        while i < length - 3:
            if data[i:i + 4] == b"\x00\x00\x00\x01":
                starts.append(i + 4)
                i += 4
                continue

            if data[i:i + 3] == b"\x00\x00\x01":
                starts.append(i + 3)
                i += 3
                continue

            i += 1

        if not starts:
            return [data]

        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else length

            while end > start and data[end - 1] == 0:
                end -= 1

            nal = data[start:end]
            if nal:
                nal_units.append(nal)

        return nal_units
