"""Agent-compatible facade for LazyPC's native libwebrtc backend.

This is an opt-in migration adapter. Keep the existing peer.py in place until
native media capture/encoding and the complete security/input path are ported.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import struct
from typing import Callable

from .native_connection import NativePeerConnection

PACKET_CURSOR_POSITION = 0x60


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

    def _new_transport(self) -> NativePeerConnection:
        transport = NativePeerConnection(self.dll_path)
        transport.on_text = self._dispatch_text
        transport.on_bytes = self._dispatch_bytes
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

    async def _dispatch_text(self, text: str):
        """Preserve the legacy DataChannel control protocol.

        Hardware-auth messages are routed to the dedicated Stage 3 handler
        and must not fall through to ordinary control/input handling.
        """
        try:
            control = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            control = None

        # Match peer.py: hw_auth_* is handled separately and returns early.
        if (
            isinstance(control, dict)
            and str(control.get("type", "")).startswith("hw_auth_")
        ):
            if self.on_hardware_auth_message is not None:
                await self._call(self.on_hardware_auth_message, text)
            else:
                print(
                    "[SECURITY] Received hw_auth_* message, but "
                    "on_hardware_auth_message is not configured"
                )
            return

        # Preserve graceful remote shutdown behavior.
        if text == "SESSION_CLOSE":
            print("[NATIVE-WEBRTC] Remote requested session close")
            if self.on_session_close is not None:
                asyncio.create_task(self._call(self.on_session_close))
            return

        # Preserve the legacy DataChannel liveness response.
        if text == "PING":
            if self.send_text("PONG"):
                print("[NATIVE-WEBRTC][DATA] TX -> PONG")

        if self.on_text is not None:
            await self._call(self.on_text, text)

    async def _dispatch_bytes(self, data: bytes):
        if self.on_bytes is not None:
            await self._call(self.on_bytes, data)

    async def _on_channel_open(self):
        print("[NATIVE-WEBRTC] Control channel opened")
        if self.on_channel_open is not None:
            await self._call(self.on_channel_open)
        # Cursor sync is started only after explicit Stage 3 authorization.
        self._start_cursor_sync_if_allowed()

    async def _on_channel_close(self):
        print("[NATIVE-WEBRTC] Control channel closed")

    async def _on_native_event(self, event: dict):
        event_type = event.get("type")
        state = str(event.get("data", "")).lower()
        if event_type in {"peer_connection", "connection_state"} and state in {
            "failed", "closed"
        }:
            self.security_authorized = False
            self._stop_cursor_sync()
            if self._transport is not None:
                try:
                    self._transport.native.set_video_enabled(False)
                except Exception as exc:
                    print("[NATIVE-WEBRTC] Failed to close video gate:", exc)
            if self.on_disconnected is not None:
                await self._call(self.on_disconnected)

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
        await self.signaling.send_offer(sdp)
        await self._flush_local_candidates()
        return sdp

    async def receive_offer(self, sdp: str):
        transport = await self._ensure_started()
        self._signaling_ready = False
        await transport.set_remote_description("offer", sdp)
        self._remote_description_set = True
        await self._flush_remote_candidates()
        answer = await transport.create_answer()  # native method sets local description
        await self.signaling.send_answer(answer)
        await self._flush_local_candidates()
        return answer

    async def receive_answer(self, sdp: str):
        transport = await self._ensure_started()
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
