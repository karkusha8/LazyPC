import asyncio

import av
import dxcam

from aiortc import VideoStreamTrack

from config.settings import ScreenConfig


class DesktopVideoTrack(VideoStreamTrack):

    def __init__(self):
        super().__init__()

        self._stopped = False

        # Создаём DXCam.
        #
        # OUTPUT_COLOR определяет, в каком формате DXCam
        # будет возвращать numpy-массив.
        self.camera = dxcam.create(
            output_color=ScreenConfig.OUTPUT_COLOR
        )

        # Запускаем захват рабочего стола.
        self.camera.start(
            target_fps=ScreenConfig.FPS,
            video_mode=ScreenConfig.VIDEO_MODE
        )

        print("[VIDEO] DXCam started")
        print("[VIDEO] Waiting for desktop frames...")

    async def recv(self):

        # Получаем WebRTC timestamp.
        pts, time_base = await self.next_timestamp()

        if self._stopped:
            raise RuntimeError(
                "DesktopVideoTrack is stopped"
            )

        image = None

        # DXCam сразу после запуска может некоторое время
        # возвращать None.
        #
        # Ждём появления реального кадра.
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

        # Создаём настоящий VideoFrame из кадра DXCam.
        frame = av.VideoFrame.from_ndarray(
            image,
            format="rgb24"
        )

        # Передаём WebRTC правильные timestamps.
        frame.pts = pts
        frame.time_base = time_base

        return frame

    def stop(self):

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