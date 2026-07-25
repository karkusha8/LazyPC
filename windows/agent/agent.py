from backends.windows import WindowsBackend

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


        # ============================================================
        # DATACHANNEL
        # ============================================================


        self.peer.on_bytes = (

            self._handle_input_packet
        )


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


        print(
            "=" * 40
        )

        print(
            "LazyPC Agent"
        )

        print(
            "=" * 40
        )


        await self.signaling.connect()


        await self.peer.create_offer()


        print(
            "[AGENT] Ready"
        )


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


            packet_type = (
                data[0]
            )


            payload = (
                data[1:]
            )


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


    async def stop(
        self
    ):


        print(
            "[AGENT] Stopping"
        )


        try:

            await self.peer.close()


        finally:

            await self.signaling.close()


        print(
            "[AGENT] Stopped"
        )


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