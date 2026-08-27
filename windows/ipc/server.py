import asyncio
import json
from typing import Awaitable, Callable, Optional

import websockets
from websockets.server import ServerConnection


MessageHandler = Callable[
    [dict],
    Optional[dict] | Awaitable[Optional[dict]],
]


class WebSocketServer:
    HOST = "127.0.0.1"
    PORT = 8765
    PATH = "/ui"

    def __init__(
        self,
        on_message: Optional[MessageHandler] = None,
    ):
        self.on_message = on_message

        self._server = None
        self._client: ServerConnection | None = None
        self._client_lock = asyncio.Lock()

    async def start(self) -> None:
        if self._server is not None:
            return

        self._server = await websockets.serve(
            self._handle_client,
            self.HOST,
            self.PORT,
        )

        print(
            f"[IPC] WebSocket server started: "
            f"ws://{self.HOST}:{self.PORT}{self.PATH}"
        )

    async def stop(self) -> None:
        client = self._client

        if client is not None:
            try:
                await client.close()
            except Exception:
                pass

        self._client = None

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        print("[IPC] WebSocket server stopped")

    async def send(
        self,
        message: dict,
    ) -> bool:
        client = self._client

        if client is None:
            print(
                "[IPC] Send skipped: UI is not connected"
            )
            return False

        try:
            payload = json.dumps(
                message,
                separators=(",", ":"),
            )

            async with self._client_lock:
                # UI could disconnect while waiting for the lock.
                if self._client is not client:
                    return False

                await client.send(payload)

            print(
                "[IPC] Agent -> UI:",
                message.get("type", "<unknown>"),
            )

            return True

        except Exception as error:
            print(
                "[IPC] Agent -> UI send failed:",
                error,
            )

            if self._client is client:
                self._client = None

            return False

    async def _handle_client(
        self,
        websocket: ServerConnection,
    ) -> None:
        # We currently support one Windows UI instance.
        if self._client is not None:
            print(
                "[IPC] Rejecting second UI connection"
            )

            await websocket.close(
                code=1013,
                reason="UI already connected",
            )

            return

        self._client = websocket

        print("[IPC] UI connected")

        try:
            await websocket.send(
                json.dumps(
                    {
                        "type": "ipc_ready",
                    },
                    separators=(",", ":"),
                )
            )

            async for raw_message in websocket:
                await self._handle_message(
                    raw_message
                )

        except websockets.ConnectionClosed:
            pass

        except Exception as error:
            print(
                "[IPC] UI connection error:",
                error,
            )

        finally:
            if self._client is websocket:
                self._client = None

            print("[IPC] UI disconnected")

    async def _handle_message(
        self,
        raw_message: str | bytes,
    ) -> None:
        try:
            if isinstance(raw_message, bytes):
                raw_message = raw_message.decode(
                    "utf-8"
                )

            message = json.loads(raw_message)

        except Exception as error:
            print(
                "[IPC] Invalid JSON from UI:",
                error,
            )
            return

        if not isinstance(message, dict):
            print(
                "[IPC] Ignoring non-object message"
            )
            return

        message_type = message.get(
            "type",
            "<unknown>",
        )

        print(
            "[IPC] UI -> Agent:",
            message_type,
        )

        if self.on_message is None:
            return

        try:
            result = self.on_message(message)

            if asyncio.iscoroutine(result):
                result = await result

            if result is not None:
                await self.send(result)

        except Exception as error:
            print(
                "[IPC] Message handler failed:",
                error,
            )