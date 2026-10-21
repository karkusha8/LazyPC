"""Agent-compatible facade for LazyPC's native libwebrtc backend.

This is an opt-in migration adapter. Keep the existing peer.py in place until
native media capture/encoding and the complete security/input path are ported.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
import struct
from typing import Callable

from .native_connection import NativePeerConnection

PACKET_CURSOR_POSITION = 0x60


def _log_video_codecs(label: str, sdp: str) -> None:
    """Log a compact video-codec summary without dumping SDP internals."""
    in_video = False
    payload_to_codec: dict[str, str] = {}
    video_payloads: list[str] = []
    direction = "unknown"

    for raw_line in sdp.splitlines():
        line = raw_line.strip()
        if line.startswith("m="):
            in_video = line.startswith("m=video ")
            if in_video:
                fields = line.split()
                video_payloads = fields[3:]
            continue
        if not in_video:
            continue
        match = re.match(r"a=rtpmap:(\d+)\s+([^/\s]+)", line)
        if match:
            payload_to_codec[match.group(1)] = match.group(2)
        elif line in ("a=sendrecv", "a=sendonly", "a=recvonly", "a=inactive"):
            direction = line[2:]

    codecs: list[str] = []
    for payload in video_payloads:
        codec = payload_to_codec.get(payload)
        if codec and codec.lower() not in ("rtx", "red", "ulpfec", "flexfec-03") and codec not in codecs:
            codecs.append(codec)
    codec_summary = ", ".join(codecs) if codecs else "not listed"
    print(f"[LazyPC-SDP] {label}: video codecs={codec_summary}; direction={direction}")


class PeerConnection:
    """Compatibility facade matching the methods Agent expects from peer.py.

    Native libwebrtc transport with desktop video capture gated by Stage 3 auth.
    Audio capture is not implemented in this native adapter yet.
    """

    def __init__(self, signaling, dll_path: str | None = None):
        self.signaling = signaling
        self.dll_path = dll_path
        self._transport: NativePeerConnection | None = None
        self._started = False
        self._closing = False
        self._stopping = False
        self._disconnect_notified = False
        self._remote_description_set = False
        self._pending_remote_candidates: list[dict] = []
        self._pending_local_candidates: list[dict] = []
        self._signaling_ready = False
        self._cursor_sync_task: asyncio.Task | None = None
        self.cursor_position_provider: Callable | None = None
        self.security_authorized = False

        self.on_text: Callable | None = None
        self.on_bytes: Callable | None = None
        self.on_disconnected: Callable | None = None
        self.on_session_close: Callable | None = None
        self.on_channel_open: Callable | None = None
        self.on_hardware_auth_message: Callable | None = None
        self.on_auth_channel_open: Callable | None = None
        self.on_auth_message: Callable | None = None

    def _new_transport(self) -> NativePeerConnection:
        transport = NativePeerConnection(self.dll_path)
        transport.on_text = self._dispatch_text
        transport.on_bytes = self._dispatch_bytes
        transport.on_auth_text = self._dispatch_auth_text
        transport.on_auth_bytes = self._dispatch_auth_bytes
        transport.on_auth_open = self._on_auth_channel_open
        transport.on_data_open = self._on_channel_open
        transport.on_data_close = self._on_channel_close
        transport.on_ice_candidate = self._on_local_candidate
        transport.on_event = self._on_native_event
        return transport

    async def _ensure_started(self) -> NativePeerConnection:
        if self._transport is None:
            self._transport = self._new_transport()
        if not self._started:
            await self._transport.start()
            self._started = True
        return self._transport

    async def _dispatch_auth_text(self, text: str):
        # The dedicated auth channel is the only pre-authorization ingress for
        # the Secure Link v4 challenge/response. It never reaches Agent's
        # general command handler.
        if self.on_auth_message is not None:
            await self._call(self.on_auth_message, text)

    async def _dispatch_auth_bytes(self, data: bytes):
        # Secure Link v4 auth messages are structured text. Drop binary frames.
        print("[SECURITY] Dropped binary frame on Trusted Device auth channel")

    async def _on_auth_channel_open(self):
        print("[NATIVE-WEBRTC] Trusted Device auth channel opened")
        if self.on_auth_channel_open is not None:
            await self._call(self.on_auth_channel_open)

    async def receive_secure_offer(self, sdp: str) -> str:
        """Accept SDP obtained only from an authenticated/decrypted Noise hello.

        Returns a fully gathered answer SDP; caller must wrap it in the Noise
        reply before sending it through its transport.
        """
        if not isinstance(sdp, str) or not sdp.strip():
            raise ValueError("Secure Link offer SDP is empty")
        if self._stopping:
            raise RuntimeError("cannot accept an offer while the previous session is stopping")
        self._disconnect_notified = False
        transport = await self._ensure_started()
        self._remote_description_set = False
        _log_video_codecs("REMOTE SECURE OFFER", sdp)
        await transport.set_remote_description("offer", sdp)
        self._remote_description_set = True
        # Android creates the dedicated auth channel before its offer. Windows
        # creates only the control channel; both channels are then negotiated
        # on the same SCTP m-line without exposing authorization to commands.
        transport.create_control_channel()
        answer = await transport.create_answer()
        _log_video_codecs("LOCAL SECURE ANSWER", answer)
        return answer

    async def _dispatch_text(self, text: str):
        """Control channel is deaf until the Trusted Device session is authorized.

        All pre-authorization protocol traffic belongs on the dedicated `auth`
        channel. No pairing, liveness, close, or command message received on
        `control` is acted upon before the v4 authorization gate opens.
        """
        if not self.security_authorized:
            print("[SECURITY] Dropped control-channel text before Trusted Device authorization")
            return
        if self.on_text is not None:
            await self._call(self.on_text, text)

    async def _dispatch_bytes(self, data: bytes):
        # Binary DataChannel packets are used for input/control. Never pass them
        # to Agent until Stage 3 (or the enrollment StrongBox proof) succeeded.
        if not self.security_authorized:
            print("[SECURITY] Dropped binary DataChannel packet before Trusted Device authorization")
            return
        if self.on_bytes is not None:
            await self._call(self.on_bytes, data)

    async def _on_channel_open(self):
        print("[NATIVE-WEBRTC] Control channel opened")
        if self.on_channel_open is not None:
            await self._call(self.on_channel_open)
        # Cursor sync is started only after explicit Stage 3 authorization.
        self._start_cursor_sync_if_allowed()

    async def _notify_disconnected(self, source: str):
        # Ignore close events emitted by our own teardown and collapse multiple
        # native signals for the same connection into one Agent notification.
        if self._stopping or self._disconnect_notified:
            return
        self._disconnect_notified = True
        self.security_authorized = False
        self._stop_cursor_sync()
        transport = self._transport
        if transport is not None and self._started:
            try:
                await asyncio.to_thread(transport.native.set_video_enabled, False)
            except Exception as exc:
                print("[NATIVE-WEBRTC] Failed to close video gate:", exc)
        print(f"[NATIVE-WEBRTC] Disconnect detected via {source}")
        if self.on_disconnected is not None:
            await self._call(self.on_disconnected)

    async def _on_channel_close(self):
        print("[NATIVE-WEBRTC] Control channel closed; revoking session authorization")
        await self._notify_disconnected("DataChannel")

    async def _on_native_event(self, event: dict):
        event_type = event.get("type")
        state = str(event.get("data", "")).lower()
        if event_type in {"peer_connection", "connection_state"} and state in {
            "failed", "closed"
        }:
            await self._notify_disconnected(f"{event_type}={state}")

    async def _on_local_candidate(self, candidate: dict):
        # ICE gathering can begin before the offer/answer has been sent. Buffer
        # candidates so signaling order is deterministic.
        if not self._signaling_ready:
            self._pending_local_candidates.append(candidate)
            return
        await self._send_candidate(candidate)

    async def _send_candidate(self, candidate: dict):
        await self.signaling.send({
            "type": "candidate",
            "candidate": candidate["candidate"],
            "sdpMid": candidate["sdpMid"],
            "sdpMLineIndex": int(candidate["sdpMLineIndex"]),
        })

    async def _flush_local_candidates(self):
        self._signaling_ready = True
        pending, self._pending_local_candidates = self._pending_local_candidates, []
        for candidate in pending:
            await self._send_candidate(candidate)

    async def create_offer(self):
        transport = await self._ensure_started()
        if not transport.native.has_control_channel():
            transport.create_control_channel()
        self._signaling_ready = False
        sdp = await transport.create_offer()  # native method sets local description
        _log_video_codecs("LOCAL OFFER", sdp)
        await self.signaling.send_offer(sdp)
        await self._flush_local_candidates()
        return sdp

    async def receive_offer(self, sdp: str):
        transport = await self._ensure_started()
        self._signaling_ready = False
        _log_video_codecs("REMOTE OFFER", sdp)
        await transport.set_remote_description("offer", sdp)
        self._remote_description_set = True
        await self._flush_remote_candidates()
        answer = await transport.create_answer()  # native method sets local description
        _log_video_codecs("LOCAL ANSWER", answer)
        await self.signaling.send_answer(answer)
        await self._flush_local_candidates()
        return answer

    async def receive_answer(self, sdp: str):
        transport = await self._ensure_started()
        _log_video_codecs("REMOTE ANSWER", sdp)
        await transport.set_remote_description("answer", sdp)
        self._remote_description_set = True
        await self._flush_remote_candidates()

    async def add_candidate(self, candidate):
        """Accept a signaling dict or a candidate-like object for compatibility."""
        if isinstance(candidate, dict):
            message = candidate
        else:
            to_sdp = getattr(candidate, "to_sdp", None)
            message = {
                "candidate": to_sdp() if callable(to_sdp) else str(candidate),
                "sdpMid": getattr(candidate, "sdpMid", None),
                "sdpMLineIndex": getattr(candidate, "sdpMLineIndex", None),
            }
        if not self._remote_description_set:
            self._pending_remote_candidates.append(message)
            return
        transport = await self._ensure_started()
        await transport.handle_ice_signaling(message)

    async def _flush_remote_candidates(self):
        pending, self._pending_remote_candidates = self._pending_remote_candidates, []
        for candidate in pending:
            await self._ensure_started()
            await self._transport.handle_ice_signaling(candidate)

    async def handle_signaling(self, message: dict):
        message_type = message.get("type")
        if message_type == "create_session":
            await self.create_offer()
        elif message_type == "offer":
            sdp = message.get("sdp")
            if isinstance(sdp, str) and sdp:
                await self.receive_offer(sdp)
        elif message_type == "answer":
            sdp = message.get("sdp")
            if isinstance(sdp, str) and sdp:
                await self.receive_answer(sdp)
        elif message_type == "candidate":
            await self.add_candidate(message)

    def send_auth_text(self, text: str):
        if not self._started or self._transport is None:
            return False
        return self._transport.native.send_auth(text.encode("utf-8"), binary=False)

    def send_text(self, text: str):
        if not self._started or self._transport is None:
            return False
        return self._transport.send_text(text)

    def send_bytes(self, data: bytes):
        if not self._started or self._transport is None:
            return False
        return self._transport.send_bytes(data)

    def authorize_hardware_session(self):
        if not self._started or self._transport is None:
            raise RuntimeError("Cannot authorize before native WebRTC starts")
        # Fail closed: do not mark the session authorized unless native video
        # capture was successfully enabled.
        self._transport.native.set_video_enabled(True)
        self.security_authorized = True
        print("[SECURITY] Stage 3 PASS -> native video/control/cursor gates opened")
        self._start_cursor_sync_if_allowed()

    def revoke_hardware_session(self):
        self.security_authorized = False
        self._stop_cursor_sync()
        if self._transport is not None and self._started:
            try:
                self._transport.native.set_video_enabled(False)
            except Exception as exc:
                print("[NATIVE-WEBRTC] Failed to close video gate:", exc)
        print("[SECURITY] Stage 3 revoked -> native video/control/cursor gates closed")

    def _start_cursor_sync_if_allowed(self):
        if not self.security_authorized or self._cursor_sync_task is not None:
            return
        if self.cursor_position_provider is None:
            return
        self._cursor_sync_task = asyncio.create_task(self._cursor_sync_loop())

    def _stop_cursor_sync(self):
        task = self._cursor_sync_task
        self._cursor_sync_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _cursor_sync_loop(self):
        last_position = None
        try:
            while self.security_authorized:
                await asyncio.sleep(1 / 60)
                transport = self._transport
                if not self._started or transport is None:
                    continue
                try:
                    position = self.cursor_position_provider()
                except Exception as exc:
                    print("[CURSOR] Position read failed:", exc)
                    continue
                if position is None:
                    continue
                x, y = position
                current = (float(x), float(y))
                if current == last_position:
                    continue
                last_position = current
                packet = struct.pack(">Bff", PACKET_CURSOR_POSITION, *current)
                transport.send_bytes(packet)
        except asyncio.CancelledError:
            raise
        finally:
            self._cursor_sync_task = None

    async def stop_session(self):
        if self._stopping:
            return
        self._stopping = True
        self.security_authorized = False
        self._stop_cursor_sync()
        try:
            if self._transport is not None:
                try:
                    if self._started:
                        await asyncio.to_thread(
                            self._transport.native.set_video_enabled, False
                        )
                except Exception as exc:
                    print("[NATIVE-WEBRTC] Video gate close during shutdown:", exc)
                await self._transport.close()
        finally:
            self._transport = None
            self._started = False
            self._remote_description_set = False
            self._pending_remote_candidates.clear()
            self._pending_local_candidates.clear()
            self._signaling_ready = False
            self._stopping = False

    async def close(self):
        await self.stop_session()

    async def _call(self, callback, *args):
        result = callback(*args)
        if inspect.isawaitable(result):
            await result