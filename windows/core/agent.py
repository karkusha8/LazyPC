import asyncio
import json
import os
import time
import uuid

from backends.windows import WindowsBackend
from engine.gesture_engine import GestureEngine
from engine.gesture_router import GestureRouter
from engine.keyboard_state import KeyboardState

from network.signaling import SignalingClient
from core.security.identity import WindowsIdentity

from core.security.auth import AndroidAuthenticator
from core.security.connection_auth import ConnectionAuth
from core.security.trusted_pairing import TrustedPairingManager
from core.security.pairing_qr import create_pairing_qr

from webrtc.peer import PeerConnection

from ipc.server import WebSocketServer


class Agent:

    def __init__(
            self,
            signaling_url: str
    ):

        # ============================================================
        # SIGNALING
        # ============================================================

        self.windows_identity = WindowsIdentity()
        self.windows_identity.ensure_created()

        self.pc_id = self.windows_identity.device_id()

        self.signaling = (
            SignalingClient(
                signaling_url,
                self.pc_id,
            )
        )

        # ============================================================
        # SECURITY
        # ============================================================

        # Two authentication paths are intentionally kept separate:
        #
        #   AndroidAuthenticator -> existing Trusted Device V3 auth
        #   ConnectionAuth       -> manual/direct connection auth
        #
        # Trusted devices must NOT be forced through the manual UI path.
        self.trusted_authenticator = AndroidAuthenticator()
        self.connection_auth = ConnectionAuth()

        self.authenticated = False
        self.pairing_mode = False
        self.connection_mode = "ordinary"
        self.pairing = TrustedPairingManager()

        # ============================================================
        # UI APPROVAL
        # ============================================================

        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._ui_approval_future: asyncio.Future | None = None
        self._ui_approval_connection_id: str | None = None
        self._pending_auth_challenge: dict | None = None
        self._pending_manual_connection_id: str | None = None
        self._pending_manual_device_id: str | None = None

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

        # ============================================================
        # IPC
        # ============================================================

        self.ipc = WebSocketServer(
            on_message=self._handle_ipc_message
        )

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
            # ConnectionAuth challenges expire after 15 seconds.
            await asyncio.sleep(15.5)

            if self.authenticated or self._stopping:
                return

            print(
                "[SECURITY] AUTH TIMEOUT"
            )

            try:
                await self.peer.stop_session()
            except Exception as error:
                print(
                    "[SECURITY] AUTH timeout cleanup failed:",
                    error
                )

            self._clear_connection_state()

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

    # ================================================================
    # UI APPROVAL
    # ================================================================

    def _resolve_ui_approval(self, message: dict):
        future = self._ui_approval_future

        if future is None or future.done():
            return

        connection_id = message.get("connection_id")

        if connection_id != self._ui_approval_connection_id:
            return

        accepted = message.get("accepted")

        if not isinstance(accepted, bool):
            return

        future.set_result(accepted)

    async def _request_ui_approval(
            self,
            connection_id: str,
            device_id: str,
    ) -> bool:

        if self._event_loop is None:
            print("[SECURITY] UI approval unavailable")
            return False

        self._cancel_auth_timeout()

        loop = self._event_loop
        future = loop.create_future()

        self._ui_approval_future = future
        self._ui_approval_connection_id = connection_id

        request = {
            "type": "connection_request",
            "connection_id": connection_id,
            "device_id": device_id,
        }

        if not await self.ipc.send(request):
            print("[SECURITY] UI is not connected")
            self._ui_approval_future = None
            self._ui_approval_connection_id = None
            return False

        print("[SECURITY] Connection request sent to UI")

        try:
            # The UI approval is deliberately short-lived.
            accepted = await asyncio.wait_for(
                future,
                timeout=30.0,
            )
            return bool(accepted)

        except asyncio.TimeoutError:
            print("[SECURITY] UI approval timeout")
            return False

        except asyncio.CancelledError:
            raise

        finally:
            if self._ui_approval_future is future:
                self._ui_approval_future = None
                self._ui_approval_connection_id = None

    # ================================================================
    # STATE RESET
    # ================================================================

    def _clear_connection_state(self):
        self.authenticated = False
        self.pairing_mode = False
        self.connection_mode = "ordinary"
        self._cancel_auth_timeout()
        self.connection_auth.clear()

        # AndroidAuthenticator is stateless between sessions and does not
        # expose a clear() method. Do not call a non-existent API here.
        self._pending_auth_challenge = None
        self._pending_manual_connection_id = None
        self._pending_manual_device_id = None

    # ================================================================
    # SIGNALING / SECURITY
    # ================================================================

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

            self._clear_connection_state()

            pairing_token = message.get("pairing_token")

            # This mode belongs to the current session, so it must survive
            # until the later auth_response arrives.
            self.connection_mode = message.get(
                "connection_mode",
                "ordinary",
            )

            if self.connection_mode not in {
                "trusted",
                "ordinary",
            }:
                self.connection_mode = "ordinary"

            # ========================================================
            # PAIRING
            # ========================================================
            # Pairing is independent from both Trusted and Ordinary.
            # Existing pairing/enrollment logic is intentionally preserved.
            if pairing_token:
                try:
                    self.pairing.accept_signaling_token(pairing_token)
                    self.pairing_mode = True
                    self.authenticated = True

                    print(
                        "[SECURITY] Trusted Device pairing session accepted"
                    )
                    print(
                        "[SECURITY] Normal authentication bypassed ONLY for pairing"
                    )

                    await self.peer.create_offer()

                except Exception as error:
                    print(
                        "[SECURITY] PAIRING SESSION REJECTED:",
                        error
                    )

                return

            # ========================================================
            # ORDINARY / GUEST
            # ========================================================
            # Explicitly ordinary means:
            #   1. DO NOT send Trusted AUTH V3.
            #   2. Ask the Windows user for Accept / Decline.
            #   3. Only after approval start ConnectionAuth V1.
            if self.connection_mode == "ordinary":
                device_id = message.get("device_id")
                if not isinstance(device_id, str) or not device_id.strip():
                    device_id = "Android"

                connection_id = str(uuid.uuid4())

                self._pending_manual_device_id = device_id
                self._pending_manual_connection_id = connection_id

                print(
                    "[SECURITY] Ordinary connection requested"
                )
                print(
                    "[SECURITY] Trusted Device AUTH skipped "
                    "for ordinary session"
                )

                accepted = await self._request_ui_approval(
                    connection_id,
                    device_id,
                )

                if not accepted:
                    print(
                        "[SECURITY] Manual connection declined"
                    )

                    try:
                        await self.signaling.send(
                            {
                                "type": "connection_auth_rejected",
                                "version": 1,
                                "connection_id": connection_id,
                                "reason": "user_declined",
                            }
                        )
                    except Exception:
                        pass

                    try:
                        await self.peer.stop_session()
                    except Exception:
                        pass

                    self._clear_connection_state()

                    print(
                        "[AGENT] Waiting for next client..."
                    )
                    return

                print(
                    "[SECURITY] Manual connection accepted by user"
                )

                challenge = self.connection_auth.create_session()

                await self.signaling.send(
                    challenge
                )

                print(
                    "[SECURITY] Connection AUTH_CHALLENGE sent "
                    "after manual approval"
                )

                self._pending_manual_connection_id = None
                self._pending_manual_device_id = None

                self._start_auth_timeout()

                return

            # ========================================================
            # TRUSTED
            # ========================================================
            # Trusted AUTH V3 is entered only when Android explicitly
            # selected a saved Trusted PC.
            if self.connection_mode == "trusted":
                trusted_challenge = (
                    self.trusted_authenticator.challenge_payload()
                )

                print(
                    "[SECURITY] Trusted connection requested"
                )
                print(
                    "[SECURITY] Sending Trusted Device AUTH_CHALLENGE"
                )

                try:
                    await self.signaling.send(
                        trusted_challenge
                    )
                except Exception as error:
                    print(
                        "[SECURITY] Trusted AUTH_CHALLENGE send failed:",
                        error,
                    )
                    self._clear_connection_state()
                    return

                self._start_auth_timeout()

                print(
                    "[SECURITY] Waiting for Trusted Device AUTH_RESPONSE"
                )

                return

        # ============================================================
        # TRUSTED DEVICE AUTH RESPONSE (V3)
        # ============================================================

        if (
            message_type == "auth_response"
            and message.get("version") == 3
            and message.get("algorithm") == "ECDSA-P256-TRUSTED-V3"
        ):
            if self.connection_mode != "trusted":
                print(
                    "[SECURITY] Ignoring Trusted Device AUTH_RESPONSE "
                    "for non-Trusted session"
                )
                return


            self._cancel_auth_timeout()

            try:
                result = (
                    self.trusted_authenticator.verify_response(
                        message
                    )
                )

                self.authenticated = True
                self.pairing_mode = False

                print(
                    "[SECURITY] Trusted Device authentication PASS"
                )
                print(
                    "[SECURITY] Trusted device:",
                    result["device_id"],
                )
                print(
                    "[SECURITY] Trusted hardware key:",
                    "registered"
                    if result.get("hardware_public")
                    else "not registered",
                )
                print(
                    "[SECURITY] Manual approval NOT required"
                )

                await self.peer.create_offer()
                self.peer.authorize_hardware_session()

            except Exception as error:
                self.authenticated = False

                print(
                    "[SECURITY] Trusted Device authentication rejected:",
                    error,
                )
                print(
                    "[SECURITY] Trusted connection rejected; "
                    "manual approval is disabled for this session"
                )

                try:
                    await self.signaling.send(
                        {
                            "type": "trusted_auth_rejected",
                            "version": 1,
                            "reason": "trusted_auth_failed",
                        }
                    )
                except Exception:
                    pass

                try:
                    await self.peer.stop_session()
                except Exception:
                    pass

                self._clear_connection_state()

                print(
                    "[AGENT] Waiting for next client..."
                )

            return

        # ============================================================
        # ORDINARY / MANUAL AUTH RESPONSE (V1)
        # ============================================================

        if message_type == "connection_auth_response":

            self._cancel_auth_timeout()

            try:
                auth_result = (
                    self.connection_auth.verify_response(
                        message
                    )
                )

                print(
                    "[SECURITY] Android identity authenticated"
                )
                print(
                    "[SECURITY] Manual approval already passed"
                )

                # Mutual authentication for the ordinary/direct path.
                server_auth = (
                    self.connection_auth
                    .server_authentication_message()
                )

                await self.signaling.send(
                    server_auth
                )

                print(
                    "[SECURITY] Windows identity proof sent"
                )

                self.authenticated = True

                print(
                    "[SECURITY] Starting WebRTC session"
                )

                await self.peer.create_offer()
                self.peer.authorize_hardware_session()

            except Exception as error:

                self.authenticated = False

                print(
                    "[SECURITY] AUTH FAILED:",
                    error
                )

                try:
                    await self.signaling.send(
                        {
                            "type": "connection_auth_rejected",
                            "version": 1,
                            "connection_id": (
                                self.connection_auth.connection_id
                            ),
                            "reason": "authentication_failed",
                        }
                    )
                except Exception:
                    pass

                try:
                    await self.peer.stop_session()
                except Exception as cleanup_error:
                    print(
                        "[SECURITY] AUTH failure cleanup failed:",
                        cleanup_error
                    )

                self._clear_connection_state()

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
    # DATACHANNEL TEXT
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
                    json.dumps(
                        challenge,
                        separators=(",", ":")
                    )
                )

                print(
                    "[SECURITY] PAIR_CHALLENGE sent over WebRTC DataChannel"
                )

            except Exception as error:
                print(
                    "[SECURITY] PAIR_HELLO rejected:",
                    error
                )

            return

        if message_type == "pair_response":
            try:
                result = self.pairing.verify_and_register(
                    message
                )

                self.pairing_mode = False
                self.authenticated = True

                print(
                    "[SECURITY] Trusted Device enrollment PASS"
                )
                print(
                    "[SECURITY] Trusted device:",
                    result["device_id"]
                )
                print(
                    "[SECURITY] Hardware key registered"
                )

                # Pairing is now cryptographically complete. Tell the
                # Android client which public PC code belongs to this
                # Trusted Device. Signaling only transports this metadata;
                # it is NOT used as proof of trust.
                try:
                    await self.signaling.send(
                        {
                            "type": "trusted_pairing_complete",
                            "version": 1,
                            "pc_code": self.signaling.public_pc_code,
                        }
                    )

                    print(
                        "[SECURITY] Trusted PC identity sent to Android: "
                        f"{self.signaling.public_pc_code}"
                    )
                except Exception as error:
                    # Enrollment itself is already complete, so a temporary
                    # signaling notification failure must not invalidate the
                    # Trusted Device record.
                    print(
                        "[SECURITY] Failed to notify Android about "
                        "Trusted PC identity:",
                        error,
                    )

                self.peer.authorize_hardware_session()

            except Exception as error:
                self.pairing_mode = False
                self.authenticated = False

                print(
                    "[SECURITY] Trusted Device enrollment FAILED:",
                    error
                )

            return

    # ================================================================
    # IPC
    # ================================================================

    def _handle_ipc_message(self, message: dict):

        message_type = message.get("type")

        if message_type == "get_pc_info":
            return {
                "type": "pc_info",
                "pc_code": self.signaling.public_pc_code,
            }

        if message_type == "connection_response":
            if self._event_loop is not None:
                self._event_loop.call_soon_threadsafe(
                    self._resolve_ui_approval,
                    dict(message),
                )

            return None

        if message_type == "pairing_start":
            print("[IPC] Pairing requested by UI")

            try:
                result = self.start_pairing()

                return {
                    "type": "pairing_qr",
                    "success": True,
                    "path": result["path"],
                }

            except Exception as error:
                print(
                    "[IPC] Pairing start failed:",
                    error
                )

                return {
                    "type": "pairing_qr",
                    "success": False,
                    "error": str(error),
                }

        return None

    def start_pairing(self):
        # The QR MUST be created from this exact TrustedPairingManager
        # instance. Its pending invitation is later verified when the
        # Android client sends the pairing token through signaling.

        qr_path = (
            os.path.join(
                os.environ.get(
                    "LOCALAPPDATA",
                    os.path.expanduser("~")
                ),
                "LazyPC",
                "pairing",
                "trusted_device_qr.png",
            )
        )

        invitation, path = create_pairing_qr(
            self.pairing,
            qr_path,
        )

        # Tell the signaling server which Agent owns this short-lived
        # pairing token. The QR format itself stays unchanged.
        self._register_pairing_token(
            invitation.token,
            ttl_seconds=120,
        )

        print(
            "[SECURITY] ========================================"
        )
        print(
            "[SECURITY] TRUSTED DEVICE PAIRING MODE"
        )
        print(
            "[SECURITY] Pairing session created"
        )
        print(
            "[SECURITY] Expires in: 120 seconds"
        )
        print(
            "[SECURITY] QR image:",
            path
        )
        print(
            "[SECURITY] QR payload generated"
        )
        print(
            "[SECURITY] ========================================"
        )

        return {
            "path": str(path),
        }

    def _register_pairing_token(
            self,
            pairing_token: str,
            ttl_seconds: int = 120,
    ):
        """
        Register the short-lived QR token with signaling so the server can
        route Android's create_session to this exact Agent.

        The token is only a routing locator. Windows still validates the
        token cryptographically when create_session reaches this Agent.
        """
        if self._event_loop is None:
            print(
                "[SECURITY] Pairing token registration skipped: "
                "event loop unavailable"
            )
            return

        if not self.signaling.connected:
            print(
                "[SECURITY] Pairing token registration skipped: "
                "signaling disconnected"
            )
            return

        async def send_registration():
            try:
                await self.signaling.send(
                    {
                        "type": "register_pairing",
                        "version": 1,
                        "pairing_token": pairing_token,
                        "ttl_seconds": ttl_seconds,
                    }
                )

                print(
                    "[SECURITY] Pairing token registered with signaling"
                )

            except Exception as error:
                print(
                    "[SECURITY] Pairing token registration failed:",
                    error,
                )

        try:
            asyncio.run_coroutine_threadsafe(
                send_registration(),
                self._event_loop,
            )
        except Exception as error:
            print(
                "[SECURITY] Could not schedule pairing registration:",
                error,
            )

    # ================================================================
    # START
    # ================================================================

    async def start(
            self
    ):

        self._event_loop = asyncio.get_running_loop()

        print("=" * 40)
        print("LazyPC Agent")
        print("=" * 40)

        await self.signaling.connect()

        print(
            "[AGENT] Waiting for client..."
        )

        print(
            "[AGENT] Ready"
        )

        await self.ipc.start()

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

        self.keyboard_state.release_all()

    # ================================================================
    # INPUT PACKET
    # ================================================================

    def _handle_input_packet(
            self,
            data: bytes
    ):

        if self.pairing_mode:
            print(
                "[SECURITY] INPUT blocked during Trusted Device pairing"
            )
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

        except Exception as error:

            print(
                "[INPUT] Packet processing error:",
                error
            )

    # ================================================================
    # STOP
    # ================================================================

    async def stop(self):

        if self._stopping:
            return

        self._stopping = True
        self._cancel_auth_timeout()

        if (
            self._ui_approval_future is not None
            and not self._ui_approval_future.done()
        ):
            self._ui_approval_future.cancel()

        print(
            "[AGENT] Stopping"
        )

        total = time.perf_counter()

        try:

            print(
                "[DEBUG] agent -> peer.close"
            )

            t = time.perf_counter()

            await self.peer.close()

            print(
                f"[TIME] peer.close(): "
                f"{time.perf_counter() - t:.3f}s"
            )

            print(
                "[DEBUG] peer.close finished"
            )

        finally:

            self.ipc.stop()

            t = time.perf_counter()

            await self.signaling.close()

            print(
                f"[TIME] signaling.close(): "
                f"{time.perf_counter() - t:.3f}s"
            )

        self._clear_connection_state()

        print(
            f"[TIME] agent.stop(): "
            f"{time.perf_counter() - total:.3f}s"
        )

        print(
            "[AGENT] Stopped"
        )

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

        self.keyboard_state.release_all()

        self._clear_connection_state()

        await self.peer.stop_session()

        print(
            "[AGENT] Waiting for next client..."
        )

    async def _on_peer_closed(self):

        print(
            "[AGENT] Peer disconnected"
        )

        self.keyboard_state.release_all()

        self._clear_connection_state()
