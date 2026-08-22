import asyncio
import json
from typing import Awaitable, Callable, Optional

import websockets

MessageHandler = Callable[[dict], Awaitable[None]]


class SignalingClient:
    """
    LazyPC MVP signaling transport.

    Responsibilities:
      - Connect to signaling server
      - Send HELLO_AGENT
      - Exchange JSON messages
    """

    def __init__(self, url: str):

        self.url = url

        self.ws = None

        self.connected = False

        self._handler: Optional[MessageHandler] = None

        self.on_disconnect = None

    # ============================================================
    # HANDLERS
    # ============================================================

    def set_message_handler(
        self,
        handler: MessageHandler
    ):

        self._handler = handler

    def set_disconnect_handler(
        self,
        handler
    ):

        self.on_disconnect = handler

    # ============================================================
    # CONNECT
    # ============================================================

    async def connect(self):

        self.ws = await websockets.connect(self.url)

        self.connected = True

        await self.ws.send("HELLO_AGENT")

        asyncio.create_task(
            self._receive_loop()
        )

        print("[SIGNALING] Connected")

    # ============================================================
    # RECEIVE LOOP
    # ============================================================

    async def _receive_loop(self):

        try:

            async for raw in self.ws:

                try:

                    message = json.loads(raw)

                except Exception as e:

                    print(
                        "[SIGNALING] Invalid JSON:",
                        e
                    )

                    continue

                if self._handler:

                    await self._handler(
                        message
                    )

        except Exception as e:

            print(
                "[SIGNALING] Receive stopped:",
                e
            )

        finally:

            self.connected = False

            if self.on_disconnect is not None:

                try:

                    await self.on_disconnect()

                except Exception as e:

                    print(
                        "[SIGNALING] Disconnect callback error:",
                        e
                    )

    # ============================================================
    # SEND
    # ============================================================

    async def send(
        self,
        payload: dict
    ):

        if not self.connected or self.ws is None:

            raise RuntimeError(
                "Signaling is not connected"
            )

        await self.ws.send(
            json.dumps(payload)
        )

    # ============================================================
    # COMPATIBILITY API
    # ============================================================

    async def send_offer(
        self,
        sdp: str
    ):

        await self.send({

            "type": "offer",

            "sdp": sdp,
        })

    async def send_answer(
        self,
        sdp: str
    ):

        await self.send({

            "type": "answer",

            "sdp": sdp,
        })

    async def send_candidate(
        self,
        candidate
    ):

        if candidate is None:

            return

        payload = {

            "type": "candidate",

            "candidate": candidate.to_sdp(),
        }

        if hasattr(candidate, "sdpMid"):

            payload["sdpMid"] = candidate.sdpMid

        if hasattr(candidate, "sdpMLineIndex"):

            payload["sdpMLineIndex"] = candidate.sdpMLineIndex

        await self.send(
            payload
        )

    # ============================================================
    # CLOSE
    # ============================================================

    async def close(self):

        self.connected = False

        if self.ws is not None:

            await self.ws.close()