

import asyncio
import json
import os
import time

from backends.windows import WindowsBackend
from engine.gesture_engine import GestureEngine
from engine.gesture_router import GestureRouter
from engine.keyboard_state import KeyboardState

from network.signaling import SignalingClient

from security.auth import AndroidAuthenticator
from security.trusted_pairing import TrustedPairingManager
from security.pairing_qr import create_pairing_qr

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
        # SECURITY
        # ============================================================

        self.authenticator = (
            AndroidAuthenticator()
        )

        self.authenticated = False
        self.pairing_mode = False
        self.pairing = TrustedPairingManager()

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
            self._handle_signaling
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

        self.peer.on_text = self._handle_peer_text

        # ============================================================
        # PEER CLOSED CALLBACK
        # ============================================================

        self.peer.on_disconnected = self._on_peer_closed
        self.peer.on_session_close = self._on_session_close

        # ============================================================
        # CLOSE EVENT
        # ============================================================

        self._closed_event = asyncio.Event()
        self._stopping = False
        self._auth_timeout_task: asyncio.Task | None = None

        print(
            "[INPUT] DataChannel input pipeline initialized"
        )

        print(
            "[CURSOR] Cursor sync provider initialized"
        )

    # ================================================================
    # SIGNALING / SECURITY
    # ================================================================

    # ================================================================
    # AUTH TIMEOUT
    # ================================================================

    def _cancel_auth_timeout(self):
        task = self._auth_timeout_task
        self._auth_timeout_task = None

        if task is not None and not task.done():
            task.cancel()

    def _start_auth_timeout(self):
        self._cancel_auth_timeout()

        self._auth_timeout_task = asyncio.create_task(
            self._auth_timeout_watch()
        )

    async def _auth_timeout_watch(self):
        try:
            # AndroidAuthenticator uses a 15-second challenge lifetime.
            # Give the transport a small margin, then terminate the pending
            # session instead of waiting forever for AUTH_RESPONSE.
            await asyncio.sleep(15.5)

            if self.authenticated or self._stopping:
                return

            print(
                "[SECURITY] AUTH TIMEOUT: Android did not respond"
            )

            try:
                await self.peer.stop_session()
            except Exception as error:
                print(
                    "[SECURITY] AUTH timeout cleanup failed:",
                    error
                )

            self.authenticated = False
            self.pairing_mode = False

            print(
                "[AGENT] Waiting for next client..."
            )

        except asyncio.CancelledError:
            pass
        except Exception as error:
            print(
                "[SECURITY] AUTH timeout watcher failed:",
                error
            )

    async def _handle_signaling(
            self,
            message: dict
    ):

        message_type = message.get("type")

        # ============================================================
        # NEW SESSION
        # ============================================================

        if message_type == "create_session":

            print(
                "[SECURITY] Client requested session"
            )

            self.authenticated = False
            self.pairing_mode = False

            pairing_token = message.get("pairing_token")
            if pairing_token:
                try:
                    self.pairing.accept_signaling_token(pairing_token)
                    self.pairing_mode = True
                    self.authenticated = True

                    print("[SECURITY] Trusted Device pairing session accepted")
                    print("[SECURITY] Normal authentication bypassed ONLY for pairing")
                    await self.peer.create_offer()
                except Exception as error:
                    print("[SECURITY] PAIRING SESSION REJECTED:", error)
                return

            challenge = self.authenticator.challenge_payload()

            await self.signaling.send(challenge)

            print(
                "[SECURITY] AUTH_CHALLENGE sent"
            )

            self._start_auth_timeout()

            return

        # ============================================================
        # AUTH RESPONSE
        # ============================================================

        if message_type == "auth_response":

            self._cancel_auth_timeout()

            try:

                self.authenticator.verify_response(
                    message
                )

                self.authenticated = True

                print(
                    "[SECURITY] Android authenticated"
                )

                print(
                    "[SECURITY] Starting WebRTC session"
                )

                # Create the WebRTC offer with media tracks present but gated.
                # The authentication above has already passed, so we can open
                # the Stage 3 media/input gate immediately after the offer is
                # created. The actual media still cannot flow until WebRTC is
                # connected.
                await self.peer.create_offer()
                self.peer.authorize_hardware_session()

            except Exception as error:

                self.authenticated = False

                print(
                    "[SECURITY] AUTH FAILED:",
                    error
                )

                try:
                    await self.peer.stop_session()
                except Exception as cleanup_error:
                    print(
                        "[SECURITY] AUTH failure cleanup failed:",
                        cleanup_error
                    )

                print(
                    "[AGENT] Waiting for next client..."
                )

            return

        # ============================================================
        # WEBRTC
        # ============================================================

        if not self.authenticated:

            print(
                "[SECURITY] Ignoring signaling "
                "before authentication"
            )

            return

        await self.peer.handle_signaling(
            message
        )

    # ================================================================
    async def _handle_peer_text(self, text: str):

        if not self.pairing_mode:
            return

        try:
            message = json.loads(text)
        except Exception:
            return

        message_type = message.get("type")

        if message_type == "pair_hello":
            try:
                challenge = self.pairing.challenge(
                    message.get("pairing_token")
                )
                self.peer.send_text(
                    json.dumps(challenge, separators=(",", ":"))
                )
                print("[SECURITY] PAIR_CHALLENGE sent over WebRTC DataChannel")
            except Exception as error:
                print("[SECURITY] PAIR_HELLO rejected:", error)
            return

        if message_type == "pair_response":
            try:
                result = self.pairing.verify_and_register(message)
                self.pairing_mode = False
                self.authenticated = True
                print("[SECURITY] Trusted Device enrollment PASS")
                print("[SECURITY] Trusted device:", result["device_id"])
                print("[SECURITY] Hardware key registered")

                # Pairing has now completed. Open media/input only after the
                # new Trusted Device has been successfully registered.
                self.peer.authorize_hardware_session()
            except Exception as error:
                self.pairing_mode = False
                self.authenticated = False
                print("[SECURITY] Trusted Device enrollment FAILED:", error)
            return

    def start_pairing(self):
        # The QR MUST be created from this exact TrustedPairingManager
        # instance. Its _pending invitation is later verified when the
        # Android client sends the pairing token back through signaling.
        qr_path = (
            os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                "LazyPC",
                "pairing",
                "trusted_device_qr.png",
            )
        )

        invitation, path = create_pairing_qr(
            self.pairing,
            qr_path,
        )

        print("[SECURITY] ========================================")
        print("[SECURITY] TRUSTED DEVICE PAIRING MODE")
        print("[SECURITY] Pairing session created")
        print("[SECURITY] Expires in: 120 seconds")
        print("[SECURITY] QR image:", path)
        print("[SECURITY] QR payload generated")
        print("[SECURITY] ========================================")

        try:
            os.startfile(str(path))
            print("[SECURITY] QR opened in the default Windows image viewer")
        except OSError as error:
            print("[SECURITY] Could not open QR automatically:", error)

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

        # TEMPORARY TEST MODE: every Agent start creates a fresh one-time
        # Trusted Device invitation and opens its QR automatically.
        # The invitation is owned by self.pairing, so the later signaling
        # token is verified against the same in-memory pending invitation.
        self.start_pairing()

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
            "[AGENT] Signaling disconnected "
            "(WebRTC is kept alive)"
        )

        # The client may disappear without sending final KEY UP packets.
        # Signaling is only the control/negotiation transport and must not
        # determine the lifetime of the Agent or PeerConnection.
        self.keyboard_state.release_all()

    # ================================================================
    # INPUT PACKET
    # ================================================================

    def _handle_input_packet(
            self,
            data: bytes
    ):

        if self.pairing_mode:
            print("[SECURITY] INPUT blocked during Trusted Device pairing")
            return

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

        if self._stopping:
            return

        self._stopping = True
        self._cancel_auth_timeout()
        print("[AGENT] Stopping")

        total = time.perf_counter()

        try:

            print("[DEBUG] agent -> peer.close")

            t = time.perf_counter()

            await self.peer.close()

            print(
                f"[TIME] peer.close(): "
                f"{time.perf_counter() - t:.3f}s"
            )

            print("[DEBUG] peer.close finished")

        finally:

            t = time.perf_counter()

            await self.signaling.close()

            print(
                f"[TIME] signaling.close(): "
                f"{time.perf_counter() - t:.3f}s"
            )

        print(
            f"[TIME] agent.stop(): "
            f"{time.perf_counter() - total:.3f}s"
        )

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

    async def _on_session_close(self):

        print(
            "[AGENT] Client requested session close"
        )

        # Explicit close: tear down immediately instead of waiting for the
        # network-loss watchdog.
        self.keyboard_state.release_all()

        self.authenticated = False
        self._cancel_auth_timeout()

        await self.peer.stop_session()

        print(
            "[AGENT] Waiting for next client..."
        )

    async def _on_peer_closed(self):

        print(
            "[AGENT] Peer disconnected"
        )

        # No explicit SESSION_CLOSE arrived. The PeerConnection watchdog
        # decides when a temporary network loss has lasted too long.
        self.keyboard_state.release_all()

        self.authenticated = False
        self._cancel_auth_timeout()

        await self.peer.stop_session()
