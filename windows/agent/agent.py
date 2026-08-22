from backends.windows import WindowsBackend

import asyncio
import time

from engine.gesture_engine import GestureEngine
from engine.gesture_router import GestureRouter
from engine.keyboard_state import KeyboardState

from network.signaling import SignalingClient

from webrtc.peer import PeerConnection


class Agent:

    def __init__(
            self,
            signaling_url: str
    ):

        # ============================================================
        # SIGNALING
        # ============================================================

        self.signaling = (
            SignalingClient(
                signaling_url
            )
        )

        # ============================================================
        # WEBRTC
        # ============================================================

        self.peer = (
            PeerConnection(
                self.signaling
            )
        )

        # ============================================================
        # WINDOWS BACKEND
        # ============================================================

        self.input_backend = (
            WindowsBackend()
        )

        # ============================================================
        # CURSOR SYNC
        # ============================================================

        self.peer.cursor_position_provider = (
            self.input_backend
            .get_cursor_position_normalized
        )

        # ============================================================
        # MOUSE ENGINE
        # ============================================================

        self.gesture_engine = (
            GestureEngine(
                self.input_backend
            )
        )

        # ============================================================
        # KEYBOARD STATE
        # ============================================================

        self.keyboard_state = (
            KeyboardState(
                self.input_backend
            )
        )

        # ============================================================
        # INPUT ROUTER
        # ============================================================

        self.gesture_router = (
            GestureRouter(
                self.gesture_engine,
                self.keyboard_state
            )
        )

        # ============================================================
        # SIGNALING HANDLER
        # ============================================================

        self.signaling.set_message_handler(
            self.peer.handle_signaling
        )

        self.signaling.set_disconnect_handler(
            self._on_disconnect
        )

        # ============================================================
        # DATACHANNEL
        # ============================================================

        self.peer.on_bytes = (
            self._handle_input_packet
        )

        # ============================================================
        # PEER CLOSED CALLBACK
        # ============================================================

        self.peer.on_disconnected = self._on_peer_closed

        # ============================================================
        # CLOSE EVENT
        # ============================================================

        self._closed_event = asyncio.Event()

        print(
            "[INPUT] DataChannel input pipeline initialized"
        )

        print(
            "[CURSOR] Cursor sync provider initialized"
        )



    # ================================================================
    # START
    # ================================================================

    async def start(
        self
    ):

        print("=" * 40)
        print("LazyPC Agent")
        print("=" * 40)

        await self.signaling.connect()

        print("[AGENT] Waiting for client...")

        print("[AGENT] Ready")


    # ================================================================
    # WAIT CLOSED
    # ================================================================

    async def wait_closed(
        self
    ):

        await self._closed_event.wait()

    # ================================================================
    # DISCONNECT HANDLER
    # ================================================================

    async def _on_disconnect(
            self
    ):

        print(
            "[AGENT] Signaling disconnected"
        )

        # The client may disappear without sending final KEY UP packets.
        self.keyboard_state.release_all()

        self._closed_event.set()
    # ================================================================
    # INPUT PACKET
    # ================================================================

    def _handle_input_packet(

        self,

        data: bytes

    ):

        try:

            if not data:
                return

            packet_type = data[0]

            payload = data[1:]

            print(
                f"[INPUT] RX "
                f"type=0x{packet_type:02X} "
                f"payload={len(payload)} bytes"
            )

            self.gesture_router.route(
                packet_type,
                payload
            )

        except Exception as e:

            print(
                "[INPUT] Packet processing error:",
                e
            )

    # ================================================================
    # STOP
    # ================================================================

    async def stop(self):

        print("[AGENT] Stopping")

        total = time.perf_counter()

        try:
            print("[DEBUG] agent -> peer.close")
            t = time.perf_counter()
            await self.peer.close()
            print(f"[TIME] peer.close(): {time.perf_counter() - t:.3f}s")
            print("[DEBUG] peer.close finished")

        finally:

            t = time.perf_counter()
            await self.signaling.close()
            print(f"[TIME] signaling.close(): {time.perf_counter() - t:.3f}s")

        print(f"[TIME] agent.stop(): {time.perf_counter() - total:.3f}s")

        print("[AGENT] Stopped")

        self._closed_event.set()

    # ================================================================
    # SEND TEXT
    # ================================================================

    def send_text(

        self,

        text: str

    ):

        self.peer.send_text(
            text
        )

    # ================================================================
    # SEND BYTES
    # ================================================================

    def send_bytes(

        self,

        data: bytes

    ):

        self.peer.send_bytes(
            data
        )

    # ================================================================
    # PEER CLOSED
    # ================================================================

    async def _on_peer_closed(self):

        print("[AGENT] Peer disconnected")

        # WebRTC can disappear before Android sends KEY UP.
        self.keyboard_state.release_all()

        await self.peer.stop_session()

        print("[AGENT] Waiting for next client...")