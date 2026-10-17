from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Optional


class NativeWebRTCError(RuntimeError):
    pass


class NativePeer:
    """
    High-level Python wrapper around lazypc_webrtc.dll.

    This class contains no aiortc code.
    It is the first Python layer of the new native WebRTC backend.
    """

    def __init__(self, dll_path: Optional[str] = None):
        self._dll_dir_handle = None

        if dll_path is None:
            dll_path = os.environ.get("LAZYPC_WEBRTC_DLL")

        if dll_path is None:
            # Canonical project-local DLL. LAZYPC_WEBRTC_DLL remains an
            # explicit override for development and diagnostics.
            windows_root = Path(__file__).resolve().parents[2]
            dll_path = str(windows_root / "bin" / "lazypc_webrtc.dll")

        self.dll_path = Path(dll_path).expanduser().resolve()

        if not self.dll_path.exists():
            raise FileNotFoundError(
                f"LazyPC WebRTC DLL not found: {self.dll_path}"
            )

        # Python 3.8+ requires explicit DLL search directories on Windows.
        if os.name == "nt":
            try:
                self._dll_dir_handle = os.add_dll_directory(
                    str(self.dll_path.parent)
                )
            except (AttributeError, OSError):
                self._dll_dir_handle = None

        self._dll = ctypes.CDLL(str(self.dll_path))

        self._configure_api()

        self._initialized = False
        self._peer_created = False
        self._closed = False

    # ================================================================
    # DLL API
    # ================================================================

    def _configure_api(self):
        dll = self._dll

        # ------------------------------------------------------------
        # Lifecycle
        # ------------------------------------------------------------

        dll.lazypc_webrtc_init.argtypes = []
        dll.lazypc_webrtc_init.restype = ctypes.c_int

        dll.lazypc_webrtc_shutdown.argtypes = []
        dll.lazypc_webrtc_shutdown.restype = None

        dll.lazypc_webrtc_is_initialized.argtypes = []
        dll.lazypc_webrtc_is_initialized.restype = ctypes.c_int

        # ------------------------------------------------------------
        # PeerConnection
        # ------------------------------------------------------------

        dll.lazypc_webrtc_create_peer_connection.argtypes = []
        dll.lazypc_webrtc_create_peer_connection.restype = ctypes.c_int

        dll.lazypc_webrtc_close_peer_connection.argtypes = []
        dll.lazypc_webrtc_close_peer_connection.restype = None

        dll.lazypc_webrtc_has_peer_connection.argtypes = []
        dll.lazypc_webrtc_has_peer_connection.restype = ctypes.c_int

        dll.lazypc_webrtc_set_video_enabled.argtypes = [ctypes.c_int]
        dll.lazypc_webrtc_set_video_enabled.restype = ctypes.c_int

        dll.lazypc_webrtc_set_audio_enabled.argtypes = [ctypes.c_int]
        dll.lazypc_webrtc_set_audio_enabled.restype = ctypes.c_int

        # ------------------------------------------------------------
        # DataChannel
        # ------------------------------------------------------------

        dll.lazypc_webrtc_create_control_channel.argtypes = []
        dll.lazypc_webrtc_create_control_channel.restype = ctypes.c_int

        dll.lazypc_webrtc_has_control_channel.argtypes = []
        dll.lazypc_webrtc_has_control_channel.restype = ctypes.c_int

        dll.lazypc_webrtc_has_auth_channel.argtypes = []
        dll.lazypc_webrtc_has_auth_channel.restype = ctypes.c_int
        dll.lazypc_webrtc_auth_state.argtypes = []
        dll.lazypc_webrtc_auth_state.restype = ctypes.c_int
        dll.lazypc_webrtc_send_auth.argtypes = [
            ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
        ]
        dll.lazypc_webrtc_send_auth.restype = ctypes.c_int

        dll.lazypc_webrtc_send_control.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_int,
        ]
        dll.lazypc_webrtc_send_control.restype = ctypes.c_int

        dll.lazypc_webrtc_control_state.argtypes = []
        dll.lazypc_webrtc_control_state.restype = ctypes.c_int

        # ------------------------------------------------------------
        # SDP
        # ------------------------------------------------------------

        dll.lazypc_webrtc_create_offer.argtypes = [
            ctypes.POINTER(ctypes.c_void_p)
        ]
        dll.lazypc_webrtc_create_offer.restype = ctypes.c_int

        dll.lazypc_webrtc_create_answer.argtypes = [
            ctypes.POINTER(ctypes.c_void_p)
        ]
        dll.lazypc_webrtc_create_answer.restype = ctypes.c_int

        dll.lazypc_webrtc_set_remote_description.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        dll.lazypc_webrtc_set_remote_description.restype = ctypes.c_int

        dll.lazypc_webrtc_set_local_description.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        dll.lazypc_webrtc_set_local_description.restype = ctypes.c_int

        # ------------------------------------------------------------
        # ICE
        # ------------------------------------------------------------

        dll.lazypc_webrtc_add_ice_candidate.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        dll.lazypc_webrtc_add_ice_candidate.restype = ctypes.c_int

        # ------------------------------------------------------------
        # Native allocated strings
        # ------------------------------------------------------------

        dll.lazypc_webrtc_free_string.argtypes = [
            ctypes.c_void_p
        ]
        dll.lazypc_webrtc_free_string.restype = None

        # ------------------------------------------------------------
        # Event queue
        # ------------------------------------------------------------

        dll.lazypc_webrtc_next_event.argtypes = [
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_int),
        ]
        dll.lazypc_webrtc_next_event.restype = ctypes.c_int

    # ================================================================
    # LIFECYCLE
    # ================================================================

    def initialize(self):
        if self._initialized:
            return

        result = self._dll.lazypc_webrtc_init()

        if result != 1:
            raise NativeWebRTCError(
                "Failed to initialize native WebRTC"
            )

        self._initialized = True
        self._closed = False

    def shutdown(self):
        if not self._initialized:
            return

        self._dll.lazypc_webrtc_shutdown()

        self._initialized = False
        self._peer_created = False
        self._closed = True

    # ================================================================
    # PEER CONNECTION
    # ================================================================

    def create_peer_connection(self):
        self._require_initialized()

        if self.has_peer_connection():
            self._peer_created = True
            return

        result = (
            self._dll
            .lazypc_webrtc_create_peer_connection()
        )

        if result != 1:
            raise NativeWebRTCError(
                "Failed to create native PeerConnection"
            )

        self._peer_created = True

    def close_peer_connection(self):
        if not self._initialized:
            return

        if not self.has_peer_connection():
            self._peer_created = False
            return

        self._dll.lazypc_webrtc_close_peer_connection()

        self._peer_created = False

    def has_peer_connection(self) -> bool:
        return (
            self._dll
            .lazypc_webrtc_has_peer_connection()
            == 1
        )

    def set_video_enabled(self, enabled: bool) -> None:
        """Open/close the desktop-capture gate controlled by Stage 3 auth."""
        self._require_peer()
        result = self._dll.lazypc_webrtc_set_video_enabled(1 if enabled else 0)
        if result != 1:
            raise NativeWebRTCError(
                f"Failed to {'enable' if enabled else 'disable'} native video capture"
            )

    def set_audio_enabled(self, enabled: bool) -> None:
        """Open/close the native WASAPI loopback gate after Stage 3 auth."""
        self._require_peer()
        result = self._dll.lazypc_webrtc_set_audio_enabled(1 if enabled else 0)
        if result != 1:
            raise NativeWebRTCError(
                f"Failed to {'enable' if enabled else 'disable'} native system audio"
            )

    # ================================================================
    # DATA CHANNEL
    # ================================================================

    def create_control_channel(self):
        self._require_peer()

        if self.has_control_channel():
            return

        result = (
            self._dll
            .lazypc_webrtc_create_control_channel()
        )

        if result != 1:
            raise NativeWebRTCError(
                "Failed to create control DataChannel"
            )

    def has_control_channel(self) -> bool:
        return (
            self._dll
            .lazypc_webrtc_has_control_channel()
            == 1
        )

    def has_auth_channel(self) -> bool:
        self._require_peer()
        return self._dll.lazypc_webrtc_has_auth_channel() == 1

    def auth_state(self) -> int:
        self._require_peer()
        return int(self._dll.lazypc_webrtc_auth_state())

    def send_auth(self, data: bytes, binary: bool = False) -> bool:
        self._require_peer()
        if not data:
            return False
        buffer = ctypes.create_string_buffer(data)
        result = self._dll.lazypc_webrtc_send_auth(
            ctypes.cast(buffer, ctypes.c_void_p), len(data), 1 if binary else 0
        )
        return result == 1

    def control_state(self) -> int:
        """
        Native DataChannel state.

        libwebrtc enum is returned as integer.
        """

        return int(
            self._dll.lazypc_webrtc_control_state()
        )

    def send_control(
        self,
        data: bytes,
        binary: bool = True,
    ) -> bool:
        self._require_peer()

        if not data:
            return False

        buffer = ctypes.create_string_buffer(data)

        result = (
            self._dll.lazypc_webrtc_send_control(
                ctypes.cast(
                    buffer,
                    ctypes.c_void_p,
                ),
                len(data),
                1 if binary else 0,
            )
        )

        return result == 1

    def send_text(self, text: str) -> bool:
        return self.send_control(
            text.encode("utf-8"),
            binary=False,
        )

    def send_bytes(self, data: bytes) -> bool:
        return self.send_control(
            data,
            binary=True,
        )

    # ================================================================
    # SDP
    # ================================================================

    def create_offer(self) -> str:
        self._require_peer()

        sdp_ptr = ctypes.c_void_p()

        result = (
            self._dll.lazypc_webrtc_create_offer(
                ctypes.byref(sdp_ptr)
            )
        )

        if result != 1 or not sdp_ptr.value:
            raise NativeWebRTCError(
                "Native WebRTC failed to create offer"
            )

        try:
            return ctypes.string_at(
                sdp_ptr.value
            ).decode("utf-8")
        finally:
            self._dll.lazypc_webrtc_free_string(
                sdp_ptr
            )

    def create_answer(self) -> str:
        self._require_peer()

        sdp_ptr = ctypes.c_void_p()

        result = (
            self._dll.lazypc_webrtc_create_answer(
                ctypes.byref(sdp_ptr)
            )
        )

        if result != 1 or not sdp_ptr.value:
            raise NativeWebRTCError(
                "Native WebRTC failed to create answer"
            )

        try:
            return ctypes.string_at(
                sdp_ptr.value
            ).decode("utf-8")
        finally:
            self._dll.lazypc_webrtc_free_string(
                sdp_ptr
            )

    def set_remote_description(
        self,
        description_type: str,
        sdp: str,
    ):
        self._require_peer()

        result = (
            self._dll
            .lazypc_webrtc_set_remote_description(
                description_type.encode("utf-8"),
                sdp.encode("utf-8"),
            )
        )

        if result != 1:
            raise NativeWebRTCError(
                "Failed to set remote description"
            )

    def set_local_description(
        self,
        description_type: str,
        sdp: str,
    ):
        self._require_peer()

        result = (
            self._dll
            .lazypc_webrtc_set_local_description(
                description_type.encode("utf-8"),
                sdp.encode("utf-8"),
            )
        )

        if result != 1:
            raise NativeWebRTCError(
                "Failed to set local description"
            )

    # ================================================================
    # ICE
    # ================================================================

    def add_ice_candidate(
        self,
        sdp_mid: str,
        sdp_mline_index: int,
        candidate: str,
    ):
        self._require_peer()

        result = (
            self._dll
            .lazypc_webrtc_add_ice_candidate(
                sdp_mid.encode("utf-8"),
                int(sdp_mline_index),
                candidate.encode("utf-8"),
            )
        )

        if result != 1:
            raise NativeWebRTCError(
                "Failed to add ICE candidate"
            )

    # ================================================================
    # EVENTS
    # ================================================================

    def next_event(self):
        """
        Return one native WebRTC event.

        Returns:
            None
            or
            {
                "type": str,
                "data": str | bytes,
                "binary": bool,
            }
        """

        event_type_capacity = 256
        event_data_capacity = 1024 * 1024

        type_buffer = ctypes.create_string_buffer(
            event_type_capacity
        )

        data_buffer = ctypes.create_string_buffer(
            event_data_capacity
        )

        binary = ctypes.c_int(0)

        result = (
            self._dll.lazypc_webrtc_next_event(
                type_buffer,
                event_type_capacity,
                data_buffer,
                event_data_capacity,
                ctypes.byref(binary),
            )
        )

        if result == 0:
            return None

        if result < 0:
            raise NativeWebRTCError(
                "Native WebRTC event buffer is too small"
            )

        event_type = (
            type_buffer.value.decode(
                "utf-8",
                errors="replace",
            )
        )

        raw_data = data_buffer.raw[:result]

        if binary.value:
            data = bytes(raw_data)
        else:
            data = raw_data.decode(
                "utf-8",
                errors="replace",
            )

        return {
            "type": event_type,
            "data": data,
            "binary": bool(binary.value),
        }

    def drain_events(self):
        """
        Read all currently queued native events.
        """

        events = []

        while True:
            event = self.next_event()

            if event is None:
                break

            events.append(event)

        return events

    # ================================================================
    # INTERNAL
    # ================================================================

    def _require_initialized(self):
        if not self._initialized:
            raise NativeWebRTCError(
                "Native WebRTC is not initialized"
            )

    def _require_peer(self):
        self._require_initialized()

        if not self.has_peer_connection():
            raise NativeWebRTCError(
                "Native PeerConnection does not exist"
            )

    # ================================================================
    # CONTEXT / CLEANUP
    # ================================================================

    def close(self):
        if self._closed:
            return

        try:
            self.close_peer_connection()
        finally:
            self.shutdown()

            if self._dll_dir_handle is not None:
                try:
                    self._dll_dir_handle.close()
                except Exception:
                    pass

                self._dll_dir_handle = None

            self._closed = True

    def __enter__(self):
        self.initialize()
        self.create_peer_connection()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.close()