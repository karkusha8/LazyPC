import asyncio
import hashlib
import json
from typing import Optional

from fastapi import WebSocket

from app.models import AgentEntry, ClientEntry, SessionState
from app.relay import safe_close, safe_send_text


class ConnectionRegistry:
    """
    Multi-PC signaling registry.

    A PC is located by its persistent public PC ID. The registry never
    authenticates that ID; ConnectionAuth does that later.
    """

    def __init__(self) -> None:
        self._state = SessionState()
        self._lock = asyncio.Lock()

    async def register_agent(
        self,
        pc_id: str,
        ws: WebSocket,
    ) -> Optional[WebSocket]:
        async with self._lock:
            previous = self._state.agents.get(pc_id)
            self._state.agents[pc_id] = AgentEntry(
                pc_id=pc_id,
                ws=ws,
            )

            return (
                previous.ws
                if previous is not None
                else None
            )

    async def unregister_agent(
        self,
        pc_id: str,
        ws: WebSocket,
    ) -> None:
        async with self._lock:
            entry = self._state.agents.get(pc_id)

            if entry is not None and entry.ws is ws:
                self._state.agents.pop(pc_id, None)

            # Detach clients that were using this Agent.
            for client in self._state.clients.values():
                if client.pc_id == pc_id:
                    client.pc_id = None

    async def register_client(
        self,
        ws: WebSocket,
        *,
        pairing_mode: bool = False,
    ) -> None:
        async with self._lock:
            self._state.clients[ws] = ClientEntry(
                ws=ws,
                pairing_mode=pairing_mode,
            )

    async def unregister_agent(
            self,
            pc_id: str,
            ws: WebSocket,
    ) -> None:
        async with self._lock:
            entry = self._state.agents.get(pc_id)

            print(
                f"[REGISTRY] unregister_agent: "
                f"pc_id={pc_id}, "
                f"entry_exists={entry is not None}, "
                f"same_ws={entry is not None and entry.ws is ws}"
            )

            if entry is not None and entry.ws is ws:
                self._state.agents.pop(pc_id, None)

            for client in self._state.clients.values():
                if client.pc_id == pc_id:
                    client.pc_id = None

    async def set_client_pc(
            self,
            ws: WebSocket,
            pc_id: str,
            *,
            connection_mode: Optional[str] = None,
    ) -> bool:
        async with self._lock:
            client = self._state.clients.get(ws)
            agent = self._state.agents.get(pc_id)

            print(
                f"[REGISTRY] set_client_pc: "
                f"pc_id={pc_id}, "
                f"client_exists={client is not None}, "
                f"agent_exists={agent is not None}, "
                f"agents={list(self._state.agents.keys())}"
            )

            if client is None or agent is None:
                return False

            client.pc_id = pc_id
            client.connection_mode = connection_mode
            return True

    async def get_agent(
            self,
            pc_id: str,
    ) -> Optional[WebSocket]:
        async with self._lock:
            entry = self._state.agents.get(pc_id)

            print(
                f"[REGISTRY] get_agent: "
                f"pc_id={pc_id}, "
                f"found={entry is not None}, "
                f"agents={list(self._state.agents.keys())}"
            )

            if entry is None:
                return None

            return entry.ws

    async def get_client_pc(
        self,
        ws: WebSocket,
    ) -> Optional[str]:
        async with self._lock:
            client = self._state.clients.get(ws)

            if client is None:
                return None

            return client.pc_id

    async def find_pc(
        self,
        pc_id: str,
    ) -> bool:
        async with self._lock:
            return pc_id in self._state.agents

    @staticmethod
    def public_pc_code(pc_id: str) -> str:
        """
        Return the stable 9-digit user-facing PC code.

        The internal lazypc-* identity never leaves the server/agent
        boundary. The public code is deterministic, so the same PC always
        gets the same code after a server restart.
        """
        digest = hashlib.sha256(
            pc_id.encode("utf-8")
        ).digest()

        value = int.from_bytes(
            digest[:8],
            "big",
        )

        return str(
            100_000_000 +
            (value % 900_000_000)
        )

    async def resolve_pc_id(
        self,
        requested_code: str,
    ) -> Optional[str]:
        """
        Resolve ONLY the 9-digit public PC code.

        There is intentionally no fallback to:
        - internal lazypc-* IDs;
        - "the only PC online";
        - guessing.

        The mapping is deterministic and exact.
        """
        value = requested_code.strip()

        if (
            len(value) != 9
            or not value.isdigit()
        ):
            return None

        async with self._lock:
            for pc_id in self._state.agents:
                if (
                    self.public_pc_code(pc_id)
                    == value
                ):
                    return pc_id

        return None

    async def is_pc_online(
        self,
        public_code: str,
    ) -> bool:
        """Return whether the public PC code currently has a live Agent."""
        value = public_code.strip()

        if (
            len(value) != 9
            or not value.isdigit()
        ):
            return False

        async with self._lock:
            return any(
                self.public_pc_code(pc_id) == value
                for pc_id in self._state.agents
            )

    async def public_code_for_pc(
        self,
        pc_id: str,
    ) -> Optional[str]:
        async with self._lock:
            if pc_id not in self._state.agents:
                return None

            return self.public_pc_code(pc_id)

    async def pc_id_for_public_code(
        self,
        public_code: str,
    ) -> Optional[str]:
        return await self.resolve_pc_id(public_code)

    async def detach_client(

        self,
        ws: WebSocket,
    ) -> None:
        async with self._lock:
            client = self._state.clients.get(ws)

            if client is not None:
                client.pc_id = None
                client.connection_mode = None

    async def forward_client_to_agent(
        self,
        client_ws: WebSocket,
        message: str,
    ) -> bool:
        pc_id = await self.get_client_pc(client_ws)

        if pc_id is None:
            return False

        agent = await self.get_agent(pc_id)

        if agent is None:
            return False

        return await safe_send_text(
            agent,
            message,
        )

    async def forward_agent_to_client(
        self,
        pc_id: str,
        message: str,
    ) -> bool:
        async with self._lock:
            targets = [
                client.ws
                for client in self._state.clients.values()
                if client.pc_id == pc_id
            ]

        ok = False

        for client in targets:
            if await safe_send_text(client, message):
                ok = True

        return ok

    async def send_create_session(
            self,
            pc_id: str,
            *,
            connection_mode: Optional[str] = None,
    ) -> bool:
        print(
            f"[REGISTRY] send_create_session START: "
            f"pc_id={pc_id}"
        )

        agent = await self.get_agent(pc_id)

        print(
            f"[REGISTRY] send_create_session get_agent: "
            f"found={agent is not None}"
        )

        if agent is None:
            print(
                f"❌ create_session: Agent not found "
                f"for pc_id={pc_id}"
            )
            return False

        print(
            f"📤 Sending create_session to Agent: "
            f"pc_id={pc_id}"
        )

        payload = {
            "type": "create_session",
        }
        if connection_mode is not None:
            payload["connection_mode"] = connection_mode

        result = await safe_send_text(
            agent,
            json.dumps(payload, separators=(",", ":")),
        )

        print(
            f"📤 create_session send result: {result}"
        )

        return result

    async def list_pcs(self) -> list[str]:
        async with self._lock:
            return list(self._state.agents.keys())

    async def is_client_pairing(
        self,
        ws: WebSocket,
    ) -> bool:
        async with self._lock:
            client = self._state.clients.get(ws)
            return bool(
                client is not None
                and client.pairing_mode
            )


registry = ConnectionRegistry()
