from __future__ import annotations

import asyncio
import fractions
import time

import av
import dxcam

from aiortc import VideoStreamTrack

from config.settings import ScreenConfig


# WebRTC video clock.
# RTP video timestamps are normally expressed using a 90 kHz clock.
VIDEO_CLOCK_RATE = 90_000


class DesktopVideoTrack(VideoStreamTrack):
    """
    Captures the Windows desktop through DXCam and exposes it
    as an aiortc VideoStreamTrack at the configured FPS.
    """

    def __init__(self):
        super().__init__()

        self._stopped = False

        self._fps = int(ScreenConfig.FPS)

        if self._fps <= 0:
            raise ValueError(
                f"ScreenConfig.FPS must be > 0, got {self._fps}"
            )

        self._frame_interval = 1.0 / self._fps

        # RTP / WebRTC timestamp state.
        self._timestamp = 0
        self._next_frame_time: float | None = None

        # Create DXCam.
        self.camera = dxcam.create(
            output_color=ScreenConfig.OUTPUT_COLOR
        )

        # Start desktop capture.
        self.camera.start(
            target_fps=self._fps,
            video_mode=ScreenConfig.VIDEO_MODE,
        )

        print(
            f"[VIDEO] DXCam started "
            f"({self._fps} FPS, {ScreenConfig.OUTPUT_COLOR})"
        )
        print("[VIDEO] Waiting for desktop frames...")

    async def _wait_for_frame_time(self) -> None:
        """
        Pace recv() to the configured FPS.

        We don't use VideoStreamTrack.next_timestamp() here because
        we explicitly want 60 FPS instead of aiortc's default timing.
        """

        now = time.perf_counter()

        if self._next_frame_time is None:
            self._next_frame_time = now

        else:
            delay = self._next_frame_time - now

            if delay > 0:
                await asyncio.sleep(delay)

            # Advance from the previous target instead of from "now"
            # to avoid accumulating timing drift.
            self._next_frame_time += self._frame_interval

            # If capture/encoding took too long, don't try to catch up
            # with a huge number of immediately scheduled frames.
            now = time.perf_counter()

            if self._next_frame_time < now - self._frame_interval:
                self._next_frame_time = now

    async def recv(self) -> av.VideoFrame:
        if self._stopped:
            raise RuntimeError(
                "DesktopVideoTrack is stopped"
            )

        await self._wait_for_frame_time()

        if self._stopped:
            raise RuntimeError(
                "DesktopVideoTrack is stopped"
            )

        image = None

        # DXCam can return None immediately after startup.
        while image is None:
            if self._stopped:
                raise RuntimeError(
                    "DesktopVideoTrack is stopped"
                )

            image = self.camera.get_latest_frame()

            if image is None:
                await asyncio.sleep(
                    ScreenConfig.FRAME_WAIT_DELAY
                )

        # Convert DXCam's numpy image into an aiortc VideoFrame.
        frame = av.VideoFrame.from_ndarray(
            image,
            format="rgb24",
        )

        # 90 kHz WebRTC video timestamp.
        frame.pts = self._timestamp
        frame.time_base = fractions.Fraction(
            1,
            VIDEO_CLOCK_RATE,
        )

        # At 60 FPS:
        #
        # 90000 / 60 = 1500
        #
        # So timestamps are:
        #
        # 0, 1500, 3000, 4500, ...
        self._timestamp += (
            VIDEO_CLOCK_RATE // self._fps
        )

        return frame

    def stop(self) -> None:
        if self._stopped:
            return

        self._stopped = True

        try:
            self.camera.stop()
        except Exception as e:
            print(
                f"[VIDEO] DXCam stop error: {e}"
            )

        print("[VIDEO] DXCam stopped")