import asyncio
import ctypes
import hmac
import json
import os
import time
import uuid

from backends.windows import WindowsBackend
from engine.gesture_engine import GestureEngine
from engine.gesture_router import GestureRouter
from engine.keyboard_state import KeyboardState

from network.signaling import SignalingClient
from security.common.identity import WindowsIdentity
from security.common.pc_static import PcIdentity

from security.ordinary.auth import OrdinaryAuthenticator
from security.trusted.auth import SessionAuthenticator
from security.trusted.hardware_auth import HardwareWebRTCAuthenticator
from security.trusted.trusted_pairing import TrustedPairingManager
from security.trusted.signaling_transport import SecureSignalingTransport
from security.trusted.link_runner import run_pairing, serve_sessions
from security.trusted.pairing_qr import create_pairing_qr, delete_pairing_qr

from webrtc.peer_session import PeerConnection

from ipc.server import WebSocketServer
from security.trusted.pairing import TrustedDeviceStore


def _read_windows_clipboard_text() -> str | None:
    """Read CF_UNICODETEXT from the Windows clipboard; return None if unavailable."""
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.GetClipboardData.argtypes = [ctypes.c_uint]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    CF_UNICODETEXT = 13
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    except Exception:
        return None
    finally:
        user32.CloseClipboard()


def _write_windows_clipboard_text(value: str) -> bool:
    """Write text as CF_UNICODETEXT. Returns False if Windows clipboard is busy."""
    if os.name != "nt":
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_bool
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    encoded = (value + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
    if not handle:
        return False
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        return False
    try:
        ctypes.memmove(pointer, encoded, len(encoded))
    finally:
        kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            return False
        # Ownership of handle transfers to the system after SetClipboardData.
        return True
    finally:
        user32.CloseClipboard()


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

        # One persistent v4 Noise identity and one shared trusted-device store
        # must be used by both pairing and session authentication.
        self.pc_static_identity = PcIdentity()
        self.pc_static_identity.ensure_created()
        self.trusted_devices = TrustedDeviceStore(
            pc_static_pub=self.pc_static_identity.public_bytes()
        )

        self.pc_id = self.windows_identity.device_id()

        self.signaling = (
            SignalingClient(
                signaling_url,
                self.pc_id,
            )
        )

        # Secure Link v4 opaque-message transport adapter. The server must later
        # relay messages of type "secure_link" unchanged; until then the v4
        # runtime remains inactive and the adapter only buffers valid messages.
        self.secure_transport = SecureSignalingTransport(self.signaling)
        self._secure_sessions_task: asyncio.Task | None = None
        self._secure_auth_timeout_task: asyncio.Task | None = None
        self._active_secure_ctx = None
        self._secure_session_busy = False

        # ============================================================
        # SECURITY
        # ============================================================

        # Two authentication paths are intentionally kept separate:
        #
        #   AndroidAuthenticator  -> existing Trusted Device V3 auth
        #   OrdinaryAuthenticator -> Ordinary V2 manual/direct auth
        #
        # Trusted devices must NOT be forced through the manual UI path.
        self.trusted_authenticator = SessionAuthenticator(
            identity=self.pc_static_identity,
            store=self.trusted_devices,
        )
        # Retained temporarily for cleanup compatibility; v4 auth uses the
        # signed transcript handled by SessionContext on the auth DataChannel.
        self._stage3_authenticator: HardwareWebRTCAuthenticator | None = None
        self._stage3_authorized = False
        self.ordinary_authenticator = OrdinaryAuthenticator(
            identity=self.windows_identity
        )

        self.authenticated = False
        self.pairing_mode = False
        self.connection_mode = "ordinary"
        self.pairing = TrustedPairingManager(
            identity=self.pc_static_identity,
            store=self.trusted_devices,
        )

        # ============================================================
        # UI APPROVAL
        # ============================================================

        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._ui_approval_future: asyncio.Future | None = None
        self._ui_approval_connection_id: str | None = None
        self._pending_auth_challenge: dict | None = None
        self._pending_manual_connection_id: str | None = None
        self._pending_manual_device_id: str | None = None
        self._pending_manual_device: dict[str, str] | None = None

        # Secure Link v4 Trusted Device enrollment approval.
        self._pairing_task: asyncio.Task | None = None
        self._pairing_session = None
        self._pairing_qr_path: str | None = None
        self._pairing_approval_future: asyncio.Future | None = None
        self._pairing_approval_id: str | None = None

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
        self.peer.on_channel_open = self._on_peer_channel_open
        self.peer.on_hardware_auth_message = self._handle_hardware_auth_message
        self.peer.on_auth_channel_open = self._on_secure_auth_channel_open
        self.peer.on_auth_message = self._handle_secure_auth_message

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
        # One cleanup task per disconnect. Native DataChannel and
        # PeerConnection events can report the same disconnect independently.
        self._session_cleanup_task: asyncio.Task | None = None
        self._clipboard_sync_task: asyncio.Task | None = None
        self._last_clipboard_text: str | None = None
        self._last_remote_clipboard_text: str | None = None

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
            # Authentication sessions use a 60 second lifetime.
            await asyncio.sleep(60.5 if self.connection_mode == "ordinary" else 15.5)

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
            device: dict[str, str] | None = None,
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

        if device is not None:
            request["device"] = dict(device)

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
        self._stage3_authenticator = None
        self._stage3_authorized = False
        self._cancel_auth_timeout()
        self.ordinary_authenticator.clear()

        # AndroidAuthenticator is stateless between sessions and does not
        # expose a clear() method. Do not call a non-existent API here.
        self._pending_auth_challenge = None
        self._pending_manual_connection_id = None
        self._pending_manual_device_id = None
        self._pending_manual_device = None

        # Revoke the v4 session context whenever Agent state is reset.
        timeout_task = self._secure_auth_timeout_task
        self._secure_auth_timeout_task = None
        if timeout_task is not None and not timeout_task.done():
            timeout_task.cancel()
        ctx = self._active_secure_ctx
        self._active_secure_ctx = None
        self._secure_session_busy = False
        if ctx is not None:
            try:
                ctx._kill()
            except Exception:
                pass

    # ================================================================
    # SECURE LINK v4 SESSION RUNTIME
    # ================================================================

    async def _serve_secure_sessions(self):
        """Run the v4 Noise session listener over the opaque room transport."""
        while not self._stopping:
            try:
                await serve_sessions(
                    self.trusted_authenticator,
                    self.secure_transport,
                    self._build_secure_answer,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                print("[SECURITY] Secure Link session listener error:", error)
                await asyncio.sleep(1.0)

    async def _build_secure_answer(self, ctx) -> str:
        """Create an answer for the offer that was decrypted from Noise."""
        if self._secure_session_busy:
            raise RuntimeError("a Trusted Device session is already active")

        self._secure_session_busy = True
        self._active_secure_ctx = ctx
        self.authenticated = False
        self._stage3_authorized = False
        self.peer.revoke_hardware_session()
        self._start_secure_auth_timeout(ctx, timeout=30.0)

        try:
            # The offer came only from SessionAuthenticator.accept(), i.e. from
            # the authenticated Noise IK message for a registered phone.
            # PeerConnection returns a fully gathered answer; link_runner then
            # wraps it in the Noise reply before signaling transport sends it.
            return await self.peer.receive_secure_offer(ctx.offer_sdp)
        except Exception:
            timeout_task = self._secure_auth_timeout_task
            self._secure_auth_timeout_task = None
            if timeout_task is not None and not timeout_task.done():
                timeout_task.cancel()
            self._active_secure_ctx = None
            self._secure_session_busy = False
            try:
                ctx._kill()
            except Exception:
                pass
            raise

    async def _on_secure_auth_channel_open(self):
        """Send the single-use StrongBox challenge only after DTLS is up."""
        ctx = self._active_secure_ctx
        if ctx is None or self.authenticated or self._stopping:
            return

        try:
            # libwebrtc opens the SCTP DataChannel only after DTLS succeeds.
            # Its DTLS implementation validates the presented certificate
            # against the SHA-256 fingerprint in the remote SDP. That SDP was
            # carried inside the Noise hello. The native API does not yet expose
            # the negotiated remote certificate fingerprint for a second,
            # independent comparison, so this relies on libwebrtc's DTLS check.
            challenge = ctx.begin_auth(scope="session")
            self._start_secure_auth_timeout(ctx, timeout=15.5)
            sent = self.peer.send_auth_text(
                json.dumps(challenge, separators=(",", ":"))
            )
            if not sent:
                raise RuntimeError("native auth DataChannel rejected challenge")
            print("[SECURITY] Secure Link v4 challenge sent on auth DataChannel")
        except Exception as error:
            print("[SECURITY] Secure Link authorization could not start:", error)
            await self._reject_secure_session("auth_challenge_failed")

    async def _handle_secure_auth_message(self, text: str):
        ctx = self._active_secure_ctx
        if ctx is None or self.authenticated or self._stopping:
            return

        try:
            message = json.loads(text)
            if not isinstance(message, dict):
                raise ValueError("auth message must be an object")
            result = self.trusted_authenticator.authorize(ctx, message)
            if result.get("scope") != "session":
                raise RuntimeError("unexpected authorization scope")

            # The only point where protected actions become available.
            self.authenticated = True
            self._stage3_authorized = True
            timeout_task = self._secure_auth_timeout_task
            self._secure_auth_timeout_task = None
            if timeout_task is not None and not timeout_task.done():
                timeout_task.cancel()
            self.peer.authorize_hardware_session()
            self._cancel_auth_timeout()
            # Android must not mark the session ready merely because an SDP
            # track was negotiated; this authenticated ack confirms that the
            # StrongBox transcript passed and the Windows media gate is open.
            if not self.peer.send_auth_text(json.dumps(
                    {"type": "auth_complete", "scope": "session"},
                    separators=(",", ":"))):
                raise RuntimeError("native auth DataChannel rejected completion acknowledgement")
            print("[SECURITY] Secure Link v4 StrongBox authorization PASS")
        except Exception as error:
            print("[SECURITY] Secure Link v4 authorization FAILED:", error)
            await self._reject_secure_session("auth_response_invalid")

    def _start_secure_auth_timeout(self, ctx, timeout: float):
        old = self._secure_auth_timeout_task
        self._secure_auth_timeout_task = None
        if old is not None and not old.done():
            old.cancel()
        self._secure_auth_timeout_task = asyncio.create_task(
            self._secure_auth_timeout_watch(ctx, timeout),
            name="lazypc-secure-link-v4-auth-timeout",
        )

    async def _secure_auth_timeout_watch(self, ctx, timeout: float):
        try:
            await asyncio.sleep(timeout)
            if self._active_secure_ctx is ctx and not self.authenticated:
                await self._reject_secure_session("authorization_timeout")
        except asyncio.CancelledError:
            pass

    async def _reject_secure_session(self, reason: str):
        self.authenticated = False
        self._stage3_authorized = False
        timeout_task = self._secure_auth_timeout_task
        self._secure_auth_timeout_task = None
        if timeout_task is not None and not timeout_task.done():
            timeout_task.cancel()
        self.peer.revoke_hardware_session()
        ctx = self._active_secure_ctx
        self._active_secure_ctx = None
        self._secure_session_busy = False
        if ctx is not None:
            try:
                ctx._kill()
            except Exception:
                pass
        try:
            await self.peer.stop_session()
        except Exception as error:
            print("[SECURITY] Secure Link cleanup error:", error)
        print("[SECURITY] Secure Link session rejected:", reason)

    # ================================================================
    # SIGNALING / SECURITY
    # ================================================================

    async def _handle_signaling(
            self,
            message: dict
    ):

        message_type = message.get("type")

        # Secure Link v4 is the only supported WebRTC session path. Never let
        # plaintext create_session/SDP/ICE activate the legacy state machine.
        if message_type in {"create_session", "offer", "answer", "candidate"}:
            print(f"[SECURITY] Dropped legacy plaintext signaling type={message_type}")
            return

        # Route Secure Link v4 opaque messages to the per-room mailbox. These
        # bytes are not SDP JSON and must never be passed to legacy handlers.
        if message_type == "secure_link":
            self.secure_transport.feed_message(message)
            return

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
                # v4 pairing is driven by run_pairing() over opaque room bytes;
                # a legacy signaling token is not accepted as pairing proof.
                print(
                    "[SECURITY] Rejected legacy pairing-token session; "
                    "Secure Link v4 transport is required"
                )
                self._clear_connection_state()
                return

            # ========================================================
            # ORDINARY / GUEST
            # ========================================================
            # Explicitly ordinary means:
            #   1. DO NOT send Trusted AUTH V3.
            #   2. Ask the Windows user for Accept / Decline.
            #   3. Only after approval start Ordinary V2.
            if self.connection_mode == "ordinary":
                device_id = message.get("device_id")
                if not isinstance(device_id, str) or not device_id.strip():
                    device_id = "Android"

                raw_device = message.get("device")
                device: dict[str, str] | None = None

                if isinstance(raw_device, dict):
                    cleaned_device: dict[str, str] = {}

                    for key in (
                        "platform",
                        "manufacturer",
                        "model",
                        "android_version",
                    ):
                        value = raw_device.get(key)

                        if isinstance(value, str) and value.strip():
                            cleaned_device[key] = value.strip()[:128]

                    if cleaned_device:
                        device = cleaned_device

                connection_id = str(uuid.uuid4())

                self._pending_manual_device_id = device_id
                self._pending_manual_connection_id = connection_id
                self._pending_manual_device = device

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
                    device,
                )

                if not accepted:
                    print(
                        "[SECURITY] Manual connection declined"
                    )

                    try:
                        await self.signaling.send(
                            {
                                "type": "ordinary_auth_rejected",
                                "version": 2,
                                "session_id": None,
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

                challenge = self.ordinary_authenticator.create_session()

                # The one-time 9-digit secret is deliberately delivered only
                # to the local Windows UI. It is never sent through signaling.
                auth_secret = self.ordinary_authenticator.get_display_secret()

                await self.signaling.send(
                    challenge
                )

                await self.ipc.send(
                    {
                        "type": "ordinary_auth_secret",
                        "session_id": challenge["session_id"],
                        "secret": auth_secret,
                    }
                )

                print(
                    "[SECURITY] Ordinary V2 AUTH_CHALLENGE sent "
                    "after manual approval"
                )
                print(
                    "[SECURITY] One-time authentication secret delivered "
                    "to local UI"
                )

                self._pending_manual_connection_id = None
                self._pending_manual_device_id = None
                self._pending_manual_device = None

                self._start_auth_timeout()

                return

            # ========================================================
            # TRUSTED
            # ========================================================
            # Trusted AUTH V3 is entered only when Android explicitly
            # selected a saved Trusted PC.
            if self.connection_mode == "trusted":
                # The old signaling challenge API was removed in Secure Link v4.
                # SessionAuthenticator.accept() must receive the Noise hello
                # from the v4 room transport instead.
                print(
                    "[SECURITY] Trusted Device session requires Secure Link v4 "
                    "Noise hello transport; legacy signaling auth is disabled"
                )
                self._clear_connection_state()
                return

        # ============================================================
        # TRUSTED DEVICE AUTH RESPONSE (V3)
        # ============================================================

        if (
            message_type == "auth_response"
            and message.get("version") == 3
            and message.get("algorithm") == "ECDSA-P256-TRUSTED-V3"
        ):
            # Fail closed: v3 signatures are not accepted by Secure Link v4.
            print("[SECURITY] Rejected legacy Trusted Device v3 auth response")
            self.authenticated = False
            self.peer.revoke_hardware_session()
            await self.peer.stop_session()
            self._clear_connection_state()
            return

        # ============================================================
        # ORDINARY AUTH RESPONSE (V2)
        # ============================================================

        if message_type == "ordinary_auth_response":

            if self.connection_mode != "ordinary":
                return

            session_id = message.get("session_id")

            try:
                auth_result = (
                    self.ordinary_authenticator.verify_client_response(
                        message
                    )
                )

                print(
                    "[SECURITY] Ordinary V2 client authentication PASS"
                )
                print(
                    "[SECURITY] Android identity + one-time secret verified"
                )

                server_proof = (
                    self.ordinary_authenticator.build_server_proof()
                )

                await self.signaling.send(
                    server_proof
                )

                print(
                    "[SECURITY] Ordinary V2 Windows identity proof sent"
                )

                server_confirmation = (
                    self.ordinary_authenticator
                    .build_server_key_confirmation()
                )

                await self.signaling.send(
                    server_confirmation
                )

                print(
                    "[SECURITY] Ordinary V2 server key confirmation sent"
                )

                return

            except Exception as error:

                self.authenticated = False

                print(
                    "[SECURITY] Ordinary V2 AUTH FAILED:",
                    error
                )

                try:
                    await self.signaling.send(
                        {
                            "type": "ordinary_auth_rejected",
                            "version": 2,
                            "session_id": session_id,
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
        # ORDINARY KEY CONFIRMATION (V2)
        # ============================================================

        if message_type == "ordinary_key_confirmation":

            if self.connection_mode != "ordinary":
                return

            session_id = message.get("session_id")

            try:
                result = (
                    self.ordinary_authenticator
                    .verify_client_key_confirmation(message)
                )

                await self.signaling.send(result)

                self._cancel_auth_timeout()
                self.authenticated = True

                print(
                    "[SECURITY] Ordinary V2 key confirmation PASS"
                )
                print(
                    "[SECURITY] Ordinary V2 authentication COMPLETE"
                )
                print(
                    "[SECURITY] Starting WebRTC session"
                )

                await self.peer.create_offer()
                self.peer.authorize_hardware_session()

            except Exception as error:

                self.authenticated = False

                print(
                    "[SECURITY] Ordinary V2 key confirmation FAILED:",
                    error
                )

                try:
                    await self.signaling.send(
                        {
                            "type": "ordinary_auth_rejected",
                            "version": 2,
                            "session_id": session_id,
                            "reason": "key_confirmation_failed",
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
    # STAGE 3: TRUSTED HARDWARE PROOF OVER NATIVE DATACHANNEL
    # ================================================================

    async def _on_peer_channel_open(self):
        if self._clipboard_sync_task is None or self._clipboard_sync_task.done():
            self._clipboard_sync_task = asyncio.create_task(self._clipboard_sync_loop())

        # Pairing and ordinary V2 sessions retain their existing flows.
        if (
            self.connection_mode != "trusted"
            or not self.authenticated
            or self._stage3_authenticator is None
            or self._stage3_authorized
        ):
            return

        try:
            challenge = self._stage3_authenticator.begin()
            sent = self.peer.send_text(
                json.dumps(challenge, separators=(",", ":"))
            )
            if not sent:
                raise RuntimeError("Native DataChannel rejected Stage 3 challenge")
            print("[SECURITY] Stage 3 hardware challenge sent over native DataChannel")
        except Exception as error:
            print("[SECURITY] Stage 3 could not start:", error)
            await self._reject_stage3("stage3_challenge_send_failed")

    async def _handle_hardware_auth_message(self, text: str):
        # This callback is wired by PeerConnection._dispatch_text, which
        # consumes hw_auth_* messages before ordinary input/pairing handlers.
        if (
            self.connection_mode != "trusted"
            or not self.authenticated
            or self._stage3_authenticator is None
            or self._stage3_authorized
        ):
            print("[SECURITY] Ignoring Stage 3 message outside an active Trusted session")
            return

        try:
            message = json.loads(text)
            result = self._stage3_authenticator.verify_response(message)
            if result.get("status") != "AUTHORIZED":
                raise RuntimeError("Stage 3 verifier did not authorize the device")

            # Only the verified registered hardware key opens protected media.
            self.peer.authorize_hardware_session()
            self._stage3_authorized = True
            self._stage3_authenticator = None
            print("[SECURITY] Stage 3 hardware attestation PASS")
            print("[SECURITY] Native video/control/cursor gates opened")
        except Exception as error:
            print("[SECURITY] Stage 3 hardware authentication FAILED:", error)
            await self._reject_stage3("stage3_hardware_auth_failed")

    async def _reject_stage3(self, reason: str):
        self.authenticated = False
        self._stage3_authorized = False
        self._stage3_authenticator = None
        try:
            self.peer.revoke_hardware_session()
        except Exception:
            pass
        try:
            await self.signaling.send({
                "type": "trusted_auth_rejected",
                "version": 1,
                "reason": reason,
            })
        except Exception:
            pass
        try:
            await self.peer.stop_session()
        except Exception as error:
            print("[SECURITY] Failed to close rejected Stage 3 session:", error)
        self._clear_connection_state()
        print("[SECURITY] Trusted session closed: Stage 3 proof is mandatory")

    async def _clipboard_sync_loop(self):
        """Poll Windows clipboard only while the authorized control channel is active."""
        try:
            while not self._stopping:
                if getattr(self.peer, "security_authorized", False):
                    current = await asyncio.to_thread(_read_windows_clipboard_text)
                    if current is not None and current != self._last_clipboard_text:
                        self._last_clipboard_text = current
                        if current != self._last_remote_clipboard_text:
                            payload = json.dumps(
                                {"type": "clipboard_text", "text": current},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                            if self.peer.send_text(payload):
                                print("[CLIPBOARD] Windows -> Android text sent")
                await asyncio.sleep(0.6)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print("[CLIPBOARD] Windows clipboard sync stopped:", error)

    # ================================================================
    # DATACHANNEL TEXT
    # ================================================================

    async def _handle_peer_text(self, text: str):
        try:
            message = json.loads(text)
        except Exception:
            return

        message_type = message.get("type")

        # Clipboard packets arrive on the normal control channel, whose
        # PeerConnection dispatcher already drops all traffic before authorization.
        if message_type == "clipboard_text":
            if not getattr(self.peer, "security_authorized", False):
                return
            value = message.get("text")
            if not isinstance(value, str) or len(value) > 1_000_000:
                return
            if value == self._last_clipboard_text:
                return
            if await asyncio.to_thread(_write_windows_clipboard_text, value):
                self._last_remote_clipboard_text = value
                self._last_clipboard_text = value
                print("[CLIPBOARD] Android -> Windows text received")
            return

        if not self.pairing_mode:
            return

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

        if message_type in ("remove_trusted_device", "rename_trusted_device"):
            device_id = str(message.get("device_id") or "").strip()
            action = "remove" if message_type == "remove_trusted_device" else "rename"
            try:
                if not device_id:
                    raise ValueError("Missing device_id.")

                if action == "remove":
                    success = self.trusted_devices.remove(device_id)
                    if not success:
                        raise LookupError("Trusted device was not found.")
                    print(f"[IPC] Trusted Device removed: {device_id}")
                else:
                    display_name = str(message.get("display_name") or "").strip()
                    if not display_name:
                        raise ValueError("Device name cannot be empty.")
                    success = self.trusted_devices.rename(device_id, display_name)
                    if not success:
                        raise LookupError("Trusted device was not found.")
                    print(f"[IPC] Trusted Device renamed: {device_id}")

                return {
                    "type": "trusted_device_action_result",
                    "action": action,
                    "device_id": device_id,
                    "success": True,
                }
            except Exception as error:
                print(f"[IPC] Trusted Device {action} failed: {error}")
                return {
                    "type": "trusted_device_action_result",
                    "action": action,
                    "device_id": device_id,
                    "success": False,
                    "error": str(error),
                }

        if message_type == "get_trusted_devices":
            print("[IPC] UI requested Trusted Devices")

            try:
                devices = self.trusted_devices.list_devices()

                print(
                    f"[IPC] Sending {len(devices)} Trusted Device(s) to UI"
                )

                return {
                    "type": "trusted_devices",
                    "devices": devices,
                }

            except Exception as error:
                print(
                    "[IPC] Failed to load Trusted Devices:",
                    error,
                )

                return {
                    "type": "trusted_devices",
                    "success": False,
                    "devices": [],
                    "error": str(error),
                }

        if message_type == "connection_response":
            if self._event_loop is not None:
                self._event_loop.call_soon_threadsafe(
                    self._resolve_ui_approval,
                    dict(message),
                )

            return None

        if message_type == "pairing_code_response":
            self._resolve_pairing_code(message)
            return None

        if message_type == "pairing_cancel":
            task = self._pairing_task
            if task is not None and not task.done():
                task.cancel()
            return None

        if message_type == "pairing_start":
            print("[IPC] Trusted Device pairing requested by UI")
            try:
                result = self.start_pairing()
                return {
                    "type": "pairing_qr",
                    "success": True,
                    "path": result["path"],
                }
            except Exception as error:
                print("[SECURITY] Trusted Device pairing start failed:", error)
                return {
                    "type": "pairing_qr",
                    "success": False,
                    "error": str(error),
                }

        return None

    def _resolve_pairing_code(self, message: dict) -> None:
        future = self._pairing_approval_future
        if future is None or future.done():
            return
        if message.get("pairing_id") != self._pairing_approval_id:
            return
        code = message.get("code")
        if isinstance(code, str):
            # IPC may be handled from a different thread than the asyncio loop.
            loop = self._event_loop
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(
                    self._set_pairing_code_result, future, code
                )

    @staticmethod
    def _set_pairing_code_result(future: asyncio.Future, code: str) -> None:
        if not future.done():
            future.set_result(code)

    async def _enter_pairing_code(self, expected_sas: str) -> bool:
        """Ask the local user to enter the code shown on Android.

        The expected SAS is deliberately not sent to the UI. The Agent compares
        the submitted value itself before allowing the phone to enroll.
        """
        if self._event_loop is None or self._stopping:
            return False

        future = self._event_loop.create_future()
        pairing_id = str(uuid.uuid4())
        self._pairing_approval_future = future
        self._pairing_approval_id = pairing_id

        try:
            sent = await self.ipc.send({
                "type": "pairing_code_prompt",
                "pairing_id": pairing_id,
                "digits": 6,
            })
            if not sent:
                print("[SECURITY] Cannot show pairing code input: UI is disconnected")
                return False

            remaining = self._pairing_session.remaining() if self._pairing_session else 60.0
            timeout = max(0.1, min(remaining, 90.0))
            try:
                entered = await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                print("[SECURITY] Trusted Device code entry timed out")
                return False

            if not isinstance(entered, str):
                return False
            accepted = hmac.compare_digest(entered.strip(), expected_sas)
            if not accepted:
                print("[SECURITY] Trusted Device SAS code mismatch")
            else:
                print("[SECURITY] Trusted Device SAS code accepted")
            return accepted
        finally:
            if self._pairing_approval_future is future:
                self._pairing_approval_future = None
                self._pairing_approval_id = None

    async def _run_pairing_invitation(self, session, qr_path: str) -> None:
        current_task = asyncio.current_task()
        result = None
        reason = "timeout_or_rejected"
        try:
            result = await run_pairing(
                session,
                self.secure_transport,
                self._enter_pairing_code,
            )
            if result is not None:
                reason = "paired"
                print("[SECURITY] Trusted Device enrollment PASS:", result.device_id)
            else:
                print("[SECURITY] Trusted Device pairing ended without enrollment")
        except asyncio.CancelledError:
            reason = "cancelled"
            raise
        except Exception as error:
            reason = "failed"
            print("[SECURITY] Trusted Device pairing failed:", error)
        finally:
            delete_pairing_qr(qr_path)
            if self._pairing_approval_future is not None:
                future = self._pairing_approval_future
                if not future.done():
                    future.set_result(False)
            if self._pairing_task is current_task:
                self._pairing_task = None
                self._pairing_session = None
                self._pairing_qr_path = None
            try:
                await self.ipc.send({
                    "type": "pairing_finished",
                    "success": result is not None,
                    "reason": reason,
                })
            except Exception:
                pass

    def start_pairing(self):
        # Only one live QR/invitation may exist at a time.
        if self._pairing_task is not None and not self._pairing_task.done():
            raise RuntimeError("Trusted Device pairing is already active")
        if self._stopping:
            raise RuntimeError("Agent is stopping")

        qr_path = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
            "LazyPC", "pairing", "trusted_device_qr.png",
        )
        invitation, path = create_pairing_qr(self.pairing, qr_path)

        self._pairing_session = invitation.session
        self._pairing_qr_path = str(path)
        self._pairing_task = asyncio.create_task(
            self._run_pairing_invitation(invitation.session, str(path)),
            name="lazypc-trusted-device-pairing",
        )

        print("[SECURITY] Secure Link v4 Trusted Device pairing started")
        print("[SECURITY] Pairing invitation expires in 120 seconds")
        print("[SECURITY] QR image:", path)
        return {"path": str(path)}

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

        if self._secure_sessions_task is None or self._secure_sessions_task.done():
            self._secure_sessions_task = asyncio.create_task(
                self._serve_secure_sessions(),
                name="lazypc-secure-link-v4-sessions",
            )

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

        # Signaling may drop while a drag is active, even if WebRTC remains up.
        try:
            self.gesture_engine.cancel_drag()
        except Exception as error:
            print("[INPUT] Mouse drag release after signaling disconnect failed:", repr(error))
        self.keyboard_state.release_all()

    # ================================================================
    # INPUT PACKET
    # ================================================================

    def _handle_input_packet(
            self,
            data: bytes
    ):

        # Pairing must never accept remote input. In Trusted mode, the peer's
        # local gate is the source of truth: it opens only after successful
        # Stage 3 verification (or successful StrongBox-backed enrollment).
        if self.pairing_mode:
            print("[SECURITY] INPUT blocked during Trusted Device pairing")
            return

        if (
            self.connection_mode == "trusted"
            and not getattr(self.peer, "security_authorized", False)
        ):
            print("[SECURITY] INPUT blocked before Trusted Device Stage 3 authorization")
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

        if self._pairing_task is not None:
            self._pairing_task.cancel()
            try:
                await self._pairing_task
            except asyncio.CancelledError:
                pass
            self._pairing_task = None
        if self._pairing_qr_path:
            delete_pairing_qr(self._pairing_qr_path)
            self._pairing_qr_path = None

        if self._secure_sessions_task is not None:
            self._secure_sessions_task.cancel()
            try:
                await self._secure_sessions_task
            except asyncio.CancelledError:
                pass
            self._secure_sessions_task = None
        self.secure_transport.close()

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

    def _schedule_session_cleanup(self, reason: str):
        """Schedule teardown outside the native WebRTC event callback.

        NativePeerConnection.close() cancels and awaits its event-loop task.
        Running teardown from that same task can therefore self-await/deadlock.
        """
        task = self._session_cleanup_task
        if task is not None and not task.done():
            return
        self._session_cleanup_task = asyncio.create_task(
            self._cleanup_session(reason),
            name="lazypc-session-cleanup",
        )

    async def _cleanup_session(self, reason: str):
        print(f"[AGENT] Cleaning up session: {reason}")
        try:
            # DragEnd can be lost when the client disconnects mid-gesture.
            # Release the OS mouse button before stopping WebRTC.
            try:
                self.gesture_engine.cancel_drag()
            except Exception as error:
                print("[INPUT] Mouse drag release during session cleanup failed:", repr(error))
            self.keyboard_state.release_all()
            self.peer.revoke_hardware_session()
            self._clear_connection_state()
            await self.peer.stop_session()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print("[AGENT] Session cleanup error:", repr(error))
        finally:
            print("[AGENT] Waiting for next client...")

    async def _on_session_close(self):
        print("[AGENT] Client requested session close")
        self._schedule_session_cleanup("client requested close")

    async def _on_peer_closed(self):
        print("[AGENT] Peer disconnected")
        self._schedule_session_cleanup("peer disconnected")


