"""Glue between the (hostile) signaling server and the secure-link state machines.

Implement `SignalingTransport` for your real signaling client (WebSocket, etc.).
Everything that crosses it is opaque Noise bytes plus a short `kind` label; the
server learns nothing it can use and cannot forge anything.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Protocol

from .secure_link import (
    LinkError,
    PairingSession,
    PendingEnrollment,
    SessionContext,
    TrustedPhone,
    pairing_room,
)
from .auth import SessionAuthenticator


class SignalingTransport(Protocol):
    async def send(self, room: bytes, kind: str, data: bytes) -> None: ...

    async def recv(self, room: bytes) -> "tuple[str, bytes]": ...


async def run_pairing(
    session: PairingSession,
    transport: SignalingTransport,
    enter_phone_code: Callable[[str], Awaitable[bool]],
) -> "TrustedPhone | None":
    """Drive one pairing invitation to completion. Returns the paired phone, or
    None on timeout / rejection. The PC requests the code shown on the phone
    immediately after pair2, before accepting or processing pair3. Garbage from
    signaling is ignored silently."""
    room = pairing_room(session.psk)
    while True:
        left = session.remaining()
        if left <= 0:
            return None
        try:
            kind, data = await asyncio.wait_for(transport.recv(room), timeout=left)
        except asyncio.TimeoutError:
            return None
        try:
            if kind == "pair1":
                pair2 = session.handle_msg1(data)
                await transport.send(room, "pair2", pair2)
                # The phone can derive and display the same SAS only after it
                # receives pair2. The PC does not display the code; the user
                # must copy it from the phone and enter it here.
                accepted = await enter_phone_code(session.sas)
                if not accepted:
                    return None
                # The phone requires cryptographic confirmation that the Windows
                # UI accepted this exact SAS before it performs the enrollment
                # biometric/signature step. The proof is keyed by the QR PSK.
                await transport.send(room, "code_ok", session.code_accepted_proof())
            elif kind == "pair3":
                pending = session.handle_enroll(data)
                # No second Allow button: successful manual code entry is the
                # explicit user intent. Cryptographic validation still follows.
                out = pending.approve()
                await transport.send(room, "pair4", out)
                return pending.phone
        except LinkError:
            if session.finished:
                return None


async def serve_sessions(
    auth: SessionAuthenticator,
    transport: SignalingTransport,
    handler: Callable[[SessionContext], Awaitable[str]],
) -> None:
    """Accept connections from paired phones forever.

    `handler(ctx)` receives the verified offer in `ctx.offer_sdp`, must create
    the peer connection and RETURN QUICKLY with the fully gathered answer SDP
    (non-trickle ICE). Anything that continues afterwards (waiting for the
    `auth` DataChannel, ctx.begin_auth(), authorize, starting media) belongs in
    tasks the handler spawns; the Noise reply is sent as soon as it returns.
    """
    room = auth.room
    while True:
        kind, data = await transport.recv(room)
        if kind != "hello":
            continue
        try:
            ctx = auth.accept(data)
        except LinkError:
            continue                      # unknown / replayed / stale: stay silent
        asyncio.create_task(_serve_one(ctx, handler, transport, room))


async def _serve_one(ctx: SessionContext, handler, transport, room: bytes) -> None:
    try:
        answer = await handler(ctx)
        await transport.send(room, "reply", ctx.reply(answer))
    except Exception:
        ctx._kill()
