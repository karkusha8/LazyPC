from __future__ import annotations

from typing import Optional

from fastapi import WebSocket

from app.models import PeerRole, SessionState


class ConnectionRegistry:
    def __init__(self) -> None:
        self._session = SessionState()

    async def register(self, role: PeerRole, ws: WebSocket) -> Optional[WebSocket]:
        async with self._session.lock:
            previous: Optional[WebSocket] = None

            if role == PeerRole.CLIENT:
                previous = self._session.client_ws
                self._session.client_ws = ws
            elif role == PeerRole.AGENT:
                previous = self._session.agent_ws
                self._session.agent_ws = ws

            return previous

    async def unregister(self, role: PeerRole, ws: WebSocket) -> None:
        async with self._session.lock:
            if role == PeerRole.CLIENT and self._session.client_ws is ws:
                self._session.client_ws = None
            elif role == PeerRole.AGENT and self._session.agent_ws is ws:
                self._session.agent_ws = None

    async def get_peer(self, role: PeerRole) -> Optional[WebSocket]:
        async with self._session.lock:
            if role == PeerRole.CLIENT:
                peer = self._session.agent_ws
            else:
                peer = self._session.client_ws

            # 🔥 ВАЖНО: проверка жив ли сокет
            if peer is None:
                return None

            try:
                # если сокет закрыт — будет ошибка
                if peer.client_state.name != "CONNECTED":
                    return None
            except Exception:
                return None

            return peer