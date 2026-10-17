"""Opaque room-based signaling transport for Secure Link v4.

Wire envelope (server must relay this envelope without interpreting payload):
    {"type":"secure_link", "room":"<base64url>", "kind":"hello|reply|pair1..pair4",
     "data":"<base64>"}

This module deliberately does not implement or imply server support. It is the
Windows-side adapter used by link_runner once the server implements this schema.
"""
from __future__ import annotations

import asyncio
import base64
from collections import defaultdict
from typing import Any

MAX_MESSAGE_BYTES = 64 * 1024
ALLOWED_KINDS = frozenset({"hello", "reply", "pair1", "pair2", "pair3", "pair4", "code_ok"})


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_MESSAGE_BYTES * 2:
        raise ValueError("invalid base64url field")
    raw = value.encode("ascii")
    raw += b"=" * ((4 - len(raw) % 4) % 4)
    return base64.b64decode(raw, altchars=b"-_", validate=True)


def _b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64_decode(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > MAX_MESSAGE_BYTES * 2:
        raise ValueError("invalid base64 field")
    return base64.b64decode(value, validate=True)


class SecureSignalingTransport:
    """Implements link_runner.SignalingTransport over SignalingClient.send().

    Incoming envelopes are explicitly fed by Agent's signaling callback. Queues
    are bounded so a peer/server cannot grow memory without limit.
    """

    def __init__(self, client: Any, queue_limit: int = 64):
        if queue_limit < 1:
            raise ValueError("queue_limit must be positive")
        self.client = client
        self.queue_limit = queue_limit
        self._queues: dict[bytes, asyncio.Queue[tuple[str, bytes]]] = {}
        self._closed = False
        self.dropped_messages = 0
        self._subscribed_rooms: set[bytes] = set()
        self._subscribe_lock = asyncio.Lock()

    def _queue(self, room: bytes) -> asyncio.Queue[tuple[str, bytes]]:
        queue = self._queues.get(room)
        if queue is None:
            queue = asyncio.Queue(maxsize=self.queue_limit)
            self._queues[room] = queue
        return queue

    async def send(self, room: bytes, kind: str, data: bytes) -> None:
        if self._closed:
            raise RuntimeError("Secure Link transport is closed")
        if not isinstance(room, bytes) or len(room) != 16:
            raise ValueError("room must be exactly 16 bytes")
        if kind not in ALLOWED_KINDS:
            raise ValueError("unsupported Secure Link message kind")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError(
                f"Secure Link payload type is invalid: "
                f"type={type(data).__name__}, kind={kind!r}"
            )

        data = bytes(data)

        if not data or len(data) > MAX_MESSAGE_BYTES:
            raise ValueError(
                f"Secure Link payload size is invalid: "
                f"length={len(data)}, kind={kind!r}"
            )
        await self.client.send({
            "type": "secure_link",
            "room": _b64url_encode(room),
            "kind": kind,
            "data": _b64_encode(data),
        })

    async def _ensure_subscribed(self, room: bytes) -> None:
        async with self._subscribe_lock:
            if room in self._subscribed_rooms:
                return
            await self.client.send({
                "type": "secure_link_subscribe",
                "room": _b64url_encode(room),
            })
            self._subscribed_rooms.add(room)

    async def recv(self, room: bytes) -> tuple[str, bytes]:
        if self._closed:
            raise RuntimeError("Secure Link transport is closed")
        if not isinstance(room, bytes) or len(room) != 16:
            raise ValueError("room must be exactly 16 bytes")
        await self._ensure_subscribed(room)
        return await self._queue(room).get()

    def feed_message(self, message: dict) -> bool:
        """Validate and enqueue one incoming server envelope; never raises."""
        try:
            if self._closed or not isinstance(message, dict):
                raise ValueError("transport closed or malformed message")
            room = _b64url_decode(message.get("room"))
            kind = message.get("kind")
            data = _b64_decode(message.get("data"))
            if len(room) != 16:
                raise ValueError("room must be exactly 16 bytes")
            if kind not in ALLOWED_KINDS:
                raise ValueError("unsupported Secure Link message kind")
            if not data or len(data) > MAX_MESSAGE_BYTES:
                raise ValueError("Secure Link payload size is invalid")
            queue = self._queue(room)
            queue.put_nowait((kind, data))
            return True
        except (ValueError, TypeError, UnicodeError, base64.binascii.Error, asyncio.QueueFull):
            self.dropped_messages += 1
            return False

    def close(self) -> None:
        self._closed = True
        self._queues.clear()
        self._subscribed_rooms.clear()
