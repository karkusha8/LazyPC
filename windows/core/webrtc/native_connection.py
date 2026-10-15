from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from .native_peer import NativePeer, NativeWebRTCError


EventCallback = Callable[[dict], Optional[Awaitable[None]]]


class NativePeerConnection:
    """
    High-level async WebRTC connection built on top of NativePeer.

    This is the new LazyPC WebRTC layer.
    It does not depend on aiortc.
    """

    def __init__(self, dll_path: str | None = None):
        self.native = NativePeer(dll_path)

        self.on_event: Optional[EventCallback] = None

        self.on_data_open: Optional[Callable[[], object]] = None
        self.on_data_close: Optional[Callable[[], object]] = None

        self.on_text: Optional[Callable[[str], object]] = None
        self.on_bytes: Optional[Callable[[bytes], object]] = None

        # Receives a signaling-ready dict: candidate, sdpMid, sdpMLineIndex.
        self.on_ice_candidate: Optional[
            Callable[[dict], object]
        ] = None

        self.on_ice_state: Optional[
            Callable[[int], object]
        ] = None

        self.on_ice_gathering_state: Optional[
            Callable[[int], object]
        ] = None

        self.on_signaling_state: Optional[
            Callable[[int], object]
        ] = None

        self.on_connection_state: Optional[
            Callable[[str], object]
        ] = None

        self._event_task: Optional[asyncio.Task] = None
        self._running = False
        self._closed = False

    # ================================================================
    # START / STOP
    # ================================================================

    async def start(self):
        if self._running:
            return

        # DLL initialization and PeerConnection creation may block while
        # libwebrtc starts its internal threads; keep them off the event loop.
        await asyncio.to_thread(self.native.initialize)
        try:
            await asyncio.to_thread(self.native.create_peer_connection)
        except Exception:
            await asyncio.to_thread(self.native.close)
            raise

        self._running = True
        self._closed = False

        self._event_task = asyncio.create_task(
            self._event_loop(),
            name="lazypc-native-webrtc-events",
        )

        print("[NATIVE-WEBRTC] Started")

    async def close(self):
        if self._closed:
            return

        self._closed = True
        self._running = False

        print("[NATIVE-WEBRTC] Closing")

        task = self._event_task
        self._event_task = None

        if task is not None:
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

        try:
            # NativePeer.close() tears down libwebrtc and joins native threads.
            # Keep DLL teardown off the asyncio event loop, consistently with
            # initialize() and create_peer_connection() in start().
            await asyncio.to_thread(self.native.close)
        finally:
            print("[NATIVE-WEBRTC] Closed")

    # ================================================================
    # DATA CHANNEL
    # ================================================================

    def create_control_channel(self):
        self._require_running()

        self.native.create_control_channel()

        print("[NATIVE-WEBRTC] Control DataChannel created")

    def control_state(self) -> int:
        self._require_running()
        return self.native.control_state()

    def send_text(self, text: str) -> bool:
        self._require_running()

        return self.native.send_text(text)

    def send_bytes(self, data: bytes) -> bool:
        self._require_running()

        return self.native.send_bytes(data)

    # ================================================================
    # SDP
    # ================================================================

    async def create_offer(self) -> str:
        self._require_running()

        print("[NATIVE-WEBRTC] Creating offer")

        # The native function blocks only while libwebrtc completes
        # the operation. Keep that work away from asyncio's event loop.
        sdp = await asyncio.to_thread(
            self.native.create_offer
        )

        print("[NATIVE-WEBRTC] Offer created")

        return sdp

    async def create_answer(self) -> str:
        self._require_running()

        print("[NATIVE-WEBRTC] Creating answer")

        sdp = await asyncio.to_thread(
            self.native.create_answer
        )

        print("[NATIVE-WEBRTC] Answer created")

        return sdp

    async def set_remote_description(
        self,
        description_type: str,
        sdp: str,
    ):
        self._require_running()

        await asyncio.to_thread(
            self.native.set_remote_description,
            description_type,
            sdp,
        )

        print(
            f"[NATIVE-WEBRTC] Remote "
            f"{description_type} applied"
        )

    async def set_local_description(
        self,
        description_type: str,
        sdp: str,
    ):
        self._require_running()

        await asyncio.to_thread(
            self.native.set_local_description,
            description_type,
            sdp,
        )

        print(
            f"[NATIVE-WEBRTC] Local "
            f"{description_type} applied"
        )

    # ================================================================
    # ICE
    # ================================================================

    async def add_ice_candidate(
        self,
        sdp_mid: str,
        sdp_mline_index: int,
        candidate: str,
    ):
        self._require_running()

        await asyncio.to_thread(
            self.native.add_ice_candidate,
            sdp_mid,
            sdp_mline_index,
            candidate,
        )

    async def handle_ice_signaling(self, message: dict):
        """Apply an incoming signaling candidate using the server's JSON shape."""
        candidate = message.get("candidate")
        sdp_mid = message.get("sdpMid", message.get("sdp_mid"))
        mline_index = message.get(
            "sdpMLineIndex", message.get("sdp_mline_index")
        )

        if not isinstance(candidate, str) or not candidate:
            raise NativeWebRTCError("Signaling candidate is missing candidate SDP")
        if sdp_mid is None or mline_index is None:
            raise NativeWebRTCError(
                "Signaling candidate is missing sdpMid/sdpMLineIndex"
            )

        await self.add_ice_candidate(
            str(sdp_mid),
            int(mline_index),
            candidate,
        )

    # ================================================================
    # EVENT LOOP
    # ================================================================

    async def _event_loop(self):
        """
        Drain the native WebRTC event queue.

        Native WebRTC callbacks never call Python directly.
        They push events into the C++ queue.

        This coroutine is the bridge back into asyncio.
        """

        try:
            while self._running:
                events = self.native.drain_events()

                if events:
                    for event in events:
                        await self._dispatch_event(event)

                # Small polling interval keeps control latency low
                # without spinning a CPU core at 100%.
                await asyncio.sleep(0.005)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(
                "[NATIVE-WEBRTC] Event loop error:",
                repr(exc),
            )

    async def _dispatch_event(self, event: dict):
        event_type = event["type"]
        data = event["data"]
        binary = event["binary"]

        # ------------------------------------------------------------
        # Generic callback
        # ------------------------------------------------------------

        if self.on_event is not None:
            await self._invoke(
                self.on_event,
                event,
            )

        # ------------------------------------------------------------
        # DataChannel created / discovered
        # ------------------------------------------------------------

        if event_type == "datachannel":
            print(
                "[NATIVE-WEBRTC] DataChannel:",
                data,
            )
            return

        # ------------------------------------------------------------
        # DataChannel state
        # ------------------------------------------------------------

        if event_type == "datachannel_state":
            state = str(data)

            print(
                "[NATIVE-WEBRTC] DataChannel state:",
                state,
            )

            # libwebrtc DataStateString values:
            #
            # connecting
            # open
            # closing
            # closed
            #
            if state == "open":
                if self.on_data_open is not None:
                    await self._invoke(
                        self.on_data_open
                    )

            elif state == "closed":
                if self.on_data_close is not None:
                    await self._invoke(
                        self.on_data_close
                    )

            return

        # ------------------------------------------------------------
        # DataChannel message
        # ------------------------------------------------------------

        if event_type == "datachannel_message":

            if binary:
                if self.on_bytes is not None:
                    await self._invoke(
                        self.on_bytes,
                        bytes(data),
                    )
            else:
                if self.on_text is not None:
                    await self._invoke(
                        self.on_text,
                        str(data),
                    )

            return

        # ------------------------------------------------------------
        # ICE candidate
        # ------------------------------------------------------------

        if event_type == "ice_candidate":
            # C++ emits: sdp_mid + "\n" + mline_index + "\n" + candidate SDP.
            # Preserve all three fields: the Android/client signaling protocol
            # needs them to add the candidate to the correct media section.
            parts = str(data).split("\n", 2)
            if len(parts) != 3:
                print(
                    "[NATIVE-WEBRTC] Invalid ICE candidate event payload"
                )
                return

            sdp_mid, raw_mline_index, candidate_sdp = parts
            try:
                mline_index = int(raw_mline_index)
            except ValueError:
                print(
                    "[NATIVE-WEBRTC] Invalid ICE m-line index:",
                    raw_mline_index,
                )
                return

            candidate = {
                "candidate": candidate_sdp,
                "sdpMid": sdp_mid,
                "sdpMLineIndex": mline_index,
            }

            print(
                "[NATIVE-WEBRTC] Local ICE candidate:",
                sdp_mid,
                mline_index,
            )

            if self.on_ice_candidate is not None:
                await self._invoke(
                    self.on_ice_candidate,
                    candidate,
                )

            return

        # ------------------------------------------------------------
        # ICE connection state
        # ------------------------------------------------------------

        if event_type == "ice_connection_state":

            state = int(data)

            print(
                "[NATIVE-WEBRTC] ICE state:",
                state,
            )

            if self.on_ice_state is not None:
                await self._invoke(
                    self.on_ice_state,
                    state,
                )

            return

        # ------------------------------------------------------------
        # ICE gathering state
        # ------------------------------------------------------------

        if event_type == "ice_gathering_state":

            state = int(data)

            print(
                "[NATIVE-WEBRTC] ICE gathering state:",
                state,
            )

            if self.on_ice_gathering_state is not None:
                await self._invoke(
                    self.on_ice_gathering_state,
                    state,
                )

            return

        # ------------------------------------------------------------
        # Signaling state
        # ------------------------------------------------------------

        if event_type == "signaling_state":

            state = int(data)

            print(
                "[NATIVE-WEBRTC] Signaling state:",
                state,
            )

            if self.on_signaling_state is not None:
                await self._invoke(
                    self.on_signaling_state,
                    state,
                )

            return

        # ------------------------------------------------------------
        # PeerConnection lifecycle
        # ------------------------------------------------------------

        if event_type == "peer_connection":

            state = str(data)

            print(
                "[NATIVE-WEBRTC] PeerConnection:",
                state,
            )

            return

        # ------------------------------------------------------------
        # Renegotiation
        # ------------------------------------------------------------

        if event_type == "renegotiation_needed":

            print(
                "[NATIVE-WEBRTC] Renegotiation needed"
            )

            return

        # ------------------------------------------------------------
        # ICE receiving
        # ------------------------------------------------------------

        if event_type == "ice_receiving":

            receiving = str(data) == "1"

            print(
                "[NATIVE-WEBRTC] ICE receiving:",
                receiving,
            )

            return

        # ------------------------------------------------------------
        # Native errors
        # ------------------------------------------------------------

        if event_type == "error":

            print(
                "[NATIVE-WEBRTC] ERROR:",
                data,
            )

            return

    # ================================================================
    # CALLBACK HELPER
    # ================================================================

    async def _invoke(
        self,
        callback,
        *args,
    ):
        result = callback(*args)

        if asyncio.iscoroutine(result):
            await result

    # ================================================================
    # INTERNAL
    # ================================================================

    def _require_running(self):
        if not self._running:
            raise NativeWebRTCError(
                "NativePeerConnection is not running"
            )

    # ================================================================
    # CONTEXT MANAGER
    # ================================================================

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        await self.close()