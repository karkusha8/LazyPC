from __future__ import annotations

from typing import Optional

from fastapi import WebSocket

from app.models import PeerRole, SessionState
from app.relay import safe_send_text


class ConnectionRegistry:
    def __init__(self) -> None:
        self._session = SessionState()

    async def register(
        self,
        role: PeerRole,
        ws: WebSocket,
    ) -> Optional[WebSocket]:
        async with self._session.lock:
            previous = (
                self._session.client_ws
                if role == PeerRole.CLIENT
                else self._session.agent_ws
            )

            if role == PeerRole.CLIENT:
                self._session.client_ws = ws
            else:
                self._session.agent_ws = ws

            return previous

    async def unregister(
        self,
        role: PeerRole,
        ws: WebSocket,
    ) -> None:
        async with self._session.lock:
            if role == PeerRole.CLIENT and self._session.client_ws is ws:
                self._session.client_ws = None
                self._session.client_pairing = False
            elif role == PeerRole.AGENT and self._session.agent_ws is ws:
                self._session.agent_ws = None

    async def get_peer(
        self,
        role: PeerRole,
    ) -> Optional[WebSocket]:
        async with self._session.lock:
            peer = (
                self._session.agent_ws
                if role == PeerRole.CLIENT
                else self._session.client_ws
            )

            if peer is None:
                return None

            try:
                if peer.client_state.name != "CONNECTED":
                    return None
            except Exception:
                return None

            return peer

    async def mark_client_mode(
        self,
        ws: WebSocket,
        *,
        pairing_mode: bool,
    ) -> None:
        async with self._session.lock:
            if self._session.client_ws is ws:
                self._session.client_pairing = pairing_mode

    async def is_client_pairing(
        self,
        ws: WebSocket,
    ) -> bool:
        async with self._session.lock:
            return (
                self._session.client_ws is ws
                and self._session.client_pairing
            )

    async def notify_normal_client_connected(self) -> None:
        """
        Existing normal-session behavior.
        The server asks Windows to create a normal WebRTC session.
        """
        agent = await self.get_peer(PeerRole.CLIENT)
        if agent is None:
            return

        await safe_send_text(
            agent,
            '{"type":"create_session"}'
        )

    async def forward_to_agent(self, message: str) -> bool:
        agent = await self.get_peer(PeerRole.CLIENT)
        if agent is None:
            return False
        return await safe_send_text(agent, message)

    async def forward_to_client(self, message: str) -> bool:
        client = await self.get_peer(PeerRole.AGENT)
        if client is None:
            return False
        return await safe_send_text(client, message)


registry = ConnectionRegistry()
