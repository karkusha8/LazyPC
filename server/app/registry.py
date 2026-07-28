from __future__ import annotations

from typing import Optional

from fastapi import WebSocket

from app.models import PeerRole, SessionState


class ConnectionRegistry:
    def __init__(self) -> None:
        self._session = SessionState()

    async def register(
        self,
        role: PeerRole,
        ws: WebSocket,
    ) -> Optional[WebSocket]:

        async with self._session.lock:

            previous: Optional[WebSocket] = None

            if role == PeerRole.CLIENT:
                previous = self._session.client_ws
                self._session.client_ws = ws

            else:
                previous = self._session.agent_ws
                self._session.agent_ws = ws

            return previous

    async def unregister(
        self,
        role: PeerRole,
        ws: WebSocket,
    ) -> None:

        async with self._session.lock:

            if (
                role == PeerRole.CLIENT
                and self._session.client_ws is ws
            ):
                self._session.client_ws = None

                #
                # Старый Offer больше недействителен.
                #
                self._session.last_offer = None

            elif (
                role == PeerRole.AGENT
                and self._session.agent_ws is ws
            ):
                self._session.agent_ws = None

                #
                # Агент отключился —
                # очищаем Offer.
                #
                self._session.last_offer = None

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

    async def store_offer(self, offer: str) -> None:

        async with self._session.lock:
            self._session.last_offer = offer

    async def get_offer(self) -> Optional[str]:

        async with self._session.lock:
            return self._session.last_offer

    async def clear_offer(self) -> None:

        async with self._session.lock:
            self._session.last_offer = None

    async def notify_client_disconnected(self) -> None:

        agent = await self.get_peer(PeerRole.CLIENT)

        if agent is None:
            return

        try:
            await agent.send_json({
                "type": "client_disconnected"
            })

        except Exception:
            pass
        
registry = ConnectionRegistry()