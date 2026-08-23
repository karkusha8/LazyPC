import queue
import threading
import time

import pyaudiowpatch as pyaudio


class SystemAudioCapture:
    """
    Captures Windows system audio using WASAPI loopback.

    Audio format:
        PCM signed 16-bit
        native device sample rate
        native device channels

    IMPORTANT:
        Audio is captured using PyAudio callback mode.
        We never call stream.read(), because WASAPI loopback
        can block indefinitely when there is no playback.
    """

    CHUNK = 960

    def __init__(self):
        self._pa = None
        self._stream = None

        self._queue = queue.Queue(maxsize=10)
        self._lock = threading.Lock()

        self._started = False
        self._stopping = False

        self.sample_rate = 0
        self.channels = 0

        self.device_index = None
        self.device_name = None

        self._silence = b""

        # Realtime diagnostics.
        self._callback_blocks = 0
        self._queue_overflows = 0
        self._queue_overflow_drops = 0
        self._read_calls = 0
        self._read_underruns = 0
        self._last_depth = 0
        self._last_report = 0.0

    def start(self):
        with self._lock:
            if self._started:
                print("[AUDIO] Capture already running")
                return

            self._stopping = False

            print("[AUDIO] Initializing WASAPI loopback")

            self._pa = pyaudio.PyAudio()

            try:
                device = self._find_default_loopback_device()

                self.device_index = device["index"]
                self.device_name = device["name"]

                self.sample_rate = int(
                    device["defaultSampleRate"]
                )

                self.channels = int(
                    device["maxInputChannels"]
                )

                if self.channels <= 0:
                    raise RuntimeError(
                        "WASAPI loopback device has no input channels"
                    )

                print("[AUDIO] Loopback device:")
                print(f"[AUDIO]   index: {self.device_index}")
                print(f"[AUDIO]   name: {self.device_name}")
                print(f"[AUDIO]   sample rate: {self.sample_rate}")
                print(f"[AUDIO]   channels: {self.channels}")

                # 16-bit PCM = 2 bytes per sample.
                self._silence = bytes(
                    self.CHUNK * self.channels * 2
                )

                self._stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=self.channels,
                    rate=self.sample_rate,
                    input=True,
                    input_device_index=self.device_index,
                    frames_per_buffer=self.CHUNK,
                    stream_callback=self._audio_callback,
                )

                self._started = True

                print("[AUDIO] Capture started")

            except Exception:
                self._started = False
                self._stopping = True

                if self._stream is not None:
                    try:
                        self._stream.stop_stream()
                    except Exception:
                        pass

                    try:
                        self._stream.close()
                    except Exception:
                        pass

                    self._stream = None

                if self._pa is not None:
                    try:
                        self._pa.terminate()
                    except Exception:
                        pass

                    self._pa = None

                raise

    def _audio_callback(
        self,
        in_data,
        frame_count,
        time_info,
        status,
    ):
        """
        PyAudio callback.

        IMPORTANT:
            Never block here.
            Never call stream.read() here.
        """

        if self._stopping:
            return (
                None,
                pyaudio.paComplete,
            )

        if in_data:
            self._callback_blocks += 1

            try:
                self._queue.put_nowait(in_data)
            except queue.Full:
                # Keep the callback realtime. Drop the oldest block so the
                # queue stays close to the current playback position.
                self._queue_overflows += 1

                try:
                    self._queue.get_nowait()
                    self._queue_overflow_drops += 1
                except queue.Empty:
                    pass

                try:
                    self._queue.put_nowait(in_data)
                except queue.Full:
                    pass

        return (
            None,
            pyaudio.paContinue,
        )

    def read(self, frames=None) -> bytes:
        """
        Return one PCM block.

        The capture callback already runs at the WASAPI cadence. We wait for
        the next block, but keep detailed timing/underrun counters instead of
        silently hiding timing problems.
        """

        if frames is None:
            frames = self.CHUNK

        if frames != self.CHUNK:
            silence = bytes(
                frames * self.channels * 2
            )
        else:
            silence = self._silence

        if not self._started:
            self.start()

        if self._stopping:
            return silence

        self._read_calls += 1

        try:
            data = self._queue.get(timeout=0.05)
        except queue.Empty:
            self._read_underruns += 1

            now = time.monotonic()
            if now - self._last_report >= 1.0:
                print(
                    "[AUDIO][BUFFER] "
                    f"UNDERRUNS={self._read_underruns} "
                    f"OVERFLOWS={self._queue_overflows} "
                    f"DEPTH={self._queue.qsize()}/10"
                )
                self._last_report = now

            return silence

        self._last_depth = self._queue.qsize()

        now = time.monotonic()
        if now - self._last_report >= 1.0:
            print(
                "[AUDIO][BUFFER] "
                f"depth={self._last_depth}/10 "
                f"underruns={self._read_underruns} "
                f"overflows={self._queue_overflows} "
                f"callback_blocks={self._callback_blocks}"
            )
            self._last_report = now

        return data

    def stop(self):
        """
        Stop capture and release all WASAPI resources.

        This method is intentionally idempotent.
        """

        with self._lock:
            if (
                not self._started
                and self._stream is None
                and self._pa is None
            ):
                return

            print("[AUDIO] Capture stop: step 1 - begin")

            self._stopping = True
            self._started = False

            stream = self._stream
            pa = self._pa

            self._stream = None
            self._pa = None

        if stream is not None:
            print(
                "[AUDIO] Capture stop: "
                "step 2 - stopping stream"
            )

            try:
                if stream.is_active():
                    stream.stop_stream()
            except Exception as e:
                print(
                    f"[AUDIO] stream.stop_stream error: {e}"
                )

            print(
                "[AUDIO] Capture stop: "
                "step 3 - stream stopped"
            )

            try:
                stream.close()
            except Exception as e:
                print(
                    f"[AUDIO] stream.close error: {e}"
                )

            print(
                "[AUDIO] Capture stop: "
                "step 4 - stream closed"
            )

        if pa is not None:
            print(
                "[AUDIO] Capture stop: "
                "step 5 - terminating PyAudio"
            )

            try:
                pa.terminate()
            except Exception as e:
                print(
                    f"[AUDIO] PyAudio terminate error: {e}"
                )

            print(
                "[AUDIO] Capture stop: "
                "step 6 - PyAudio terminated"
            )

        # Remove any audio that belongs to the old session.
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        print(
            "[AUDIO] Capture stop: "
            "step 7 - queue cleared"
        )

        print(
            "[AUDIO] Capture stop: "
            "step 8 - finished"
        )

    def _find_default_loopback_device(self):
        wasapi_info = (
            self._pa.get_host_api_info_by_type(
                pyaudio.paWASAPI
            )
        )

        default_output_index = (
            wasapi_info["defaultOutputDevice"]
        )

        default_output = (
            self._pa.get_device_info_by_index(
                default_output_index
            )
        )

        print("[AUDIO] Default WASAPI output:")
        print(
            f"[AUDIO]   index: "
            f"{default_output_index}"
        )
        print(
            f"[AUDIO]   name: "
            f"{default_output['name']}"
        )
        print(
            f"[AUDIO]   sample rate: "
            f"{default_output['defaultSampleRate']}"
        )
        print(
            f"[AUDIO]   channels: "
            f"{default_output['maxOutputChannels']}"
        )

        for device in (
            self._pa.get_loopback_device_info_generator()
        ):
            if device["name"].startswith(
                default_output["name"]
            ):
                return device

        raise RuntimeError(
            "Could not find WASAPI loopback device "
            "for the default output device"
        )


def main():
    capture = SystemAudioCapture()

    try:
        print("[TEST] Starting SystemAudioCapture...")

        capture.start()

        print("[TEST] Capture started")
        print("[TEST] Play sound or leave Windows silent.")
        print("[TEST] Press Ctrl+C to stop.")
        print()

        total_frames = 0

        while True:
            data = capture.read()

            total_frames += capture.CHUNK

            print(
                f"[TEST] "
                f"frames={total_frames} "
                f"bytes={len(data)}"
            )

    except KeyboardInterrupt:
        print()
        print("[TEST] Stopping...")

    finally:
        capture.stop()
