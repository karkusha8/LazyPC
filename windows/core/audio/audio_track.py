import asyncio
from fractions import Fraction

import av
from aiortc import MediaStreamTrack

from core.audio.system_audio import SystemAudioCapture


class SystemAudioTrack(MediaStreamTrack):
    """
    aiortc audio track backed by Windows WASAPI loopback.

    Lifecycle:

        recv()
            ↓
        capture.start()

        stop()
            ↓
        остановка MediaStreamTrack

        pc.close()
            ↓
        close_capture()
            ↓
        полное освобождение WASAPI / PyAudio
    """

    kind = "audio"

    def __init__(self):
        super().__init__()

        self.capture = SystemAudioCapture()

        self.samples_per_frame = 960
        self._pts = 0

        self._started = False
        self._stopped = False
        self._capture_closed = False

    async def recv(self) -> av.AudioFrame:
        if self._stopped:
            raise asyncio.CancelledError

        if not self._started:
            self.capture.start()
            self._started = True

            print(
                "[AUDIO] AudioTrack started "
                f"({self.capture.sample_rate} Hz, "
                f"{self.capture.channels} channels)"
            )

        data = await asyncio.to_thread(
            self.capture.read,
            self.samples_per_frame,
        )

        if self._stopped:
            raise asyncio.CancelledError

        channels = self.capture.channels

        if channels == 1:
            layout = "mono"
        elif channels == 2:
            layout = "stereo"
        else:
            raise RuntimeError(
                f"Unsupported audio channel count: {channels}"
            )

        frame = av.AudioFrame(
            format="s16",
            layout=layout,
            samples=self.samples_per_frame,
        )

        frame.planes[0].update(data)

        frame.sample_rate = self.capture.sample_rate
        frame.pts = self._pts
        frame.time_base = Fraction(
            1,
            self.capture.sample_rate,
        )

        self._pts += self.samples_per_frame

        return frame

    def stop(self):
        """
        Stop only the aiortc MediaStreamTrack.

        IMPORTANT:
        WASAPI/PyAudio is NOT closed here.

        The WebRTC sender may still be using recv().
        Full capture cleanup happens only after pc.close()
        via close_capture().
        """

        if self._stopped:
            print("[AUDIO] AudioTrack.stop(): already stopped")
            return

        print("[AUDIO] AudioTrack.stop(): begin")

        self._stopped = True
        self._started = False

        super().stop()

        print("[AUDIO] AudioTrack.stop(): track stopped")

    def close_capture(self):
        """
        Fully release WASAPI/PyAudio resources.

        Must be called AFTER:
            await pc.close()
        """

        if self._capture_closed:
            print("[AUDIO] close_capture(): already closed")
            return

        self._capture_closed = True

        print("[AUDIO] close_capture(): begin")

        try:
            self.capture.stop()
        except Exception as e:
            print(
                f"[AUDIO] close_capture(): error: {e}"
            )

        print("[AUDIO] close_capture(): finished")