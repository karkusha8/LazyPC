import asyncio
import hashlib
import json
from typing import Awaitable, Callable, Optional

import websockets


MessageHandler = Callable[[dict], Awaitable[None]]


class SignalingClient:
    """
    Long-lived signaling transport for the Windows Agent.

    The persistent PC ID is a public locator only. It is registered with
    signaling after HELLO_AGENT and is NOT used as authentication.

    WebRTC messages remain unchanged:
        offer
        answer
        candidate
    """

    def __init__(
        self,
        url: str,
        pc_id: str,
    ):
        self.url = url
        self.pc_id = pc_id

        # Stable 9-digit public locator used by Android.
        digest = hashlib.sha256(
            self.pc_id.encode("utf-8")
        ).digest()

        value = int.from_bytes(
            digest[:8],
            "big",
        )

        self.public_pc_code = str(
            100_000_000 +
            (value % 900_000_000)
        )

        self.ws = None
        self.connected = False

        self._handler: Optional[MessageHandler] = None
        self.on_disconnect = None

        self._closing = False
        self._receive_task = None
        self._reconnect_task = None
        self._connect_lock = asyncio.Lock()

    def set_message_handler(
        self,
        handler: MessageHandler,
    ):
        self._handler = handler

    def set_disconnect_handler(
        self,
        handler,
    ):
        self.on_disconnect = handler

    async def connect(self):
        self._closing = False
        await self._connect_once()

    async def _connect_once(self):
        async with self._connect_lock:
            if self._closing or self.connected:
                return

            print("[SIGNALING] Connecting...")

            ws = await websockets.connect(
                self.url,
                ping_interval=15,
                ping_timeout=10,
            )

            if self._closing:
                await ws.close()
                return

            self.ws = ws
            self.connected = True

            # Existing role handshake remains unchanged.
            await ws.send("HELLO_AGENT")

            # Register the persistent public PC ID.
            await ws.send(
                json.dumps(
                    {
                        "type": "register_pc",
                        "version": 1,
                        "pc_id": self.pc_id,
                    },
                    separators=(",", ":"),
                )
            )

            self._receive_task = asyncio.create_task(
                self._receive_loop(ws)
            )

            print(
                "[SIGNALING] Connected"
            )
            print(
                f"[SIGNALING] PC CODE: "
                f"{self.public_pc_code[:3]} "
                f"{self.public_pc_code[3:6]} "
                f"{self.public_pc_code[6:]}"
            )

    async def _receive_loop(self, ws):
        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except Exception as e:
                    print(
                        "[SIGNALING] Invalid JSON:",
                        e,
                    )
                    continue

                if message.get("type") == "pc_registered":
                    server_code = str(
                        message.get(
                            "pc_code",
                            "",
                        )
                    )

                    if server_code == self.public_pc_code:
                        print(
                            "[SIGNALING] PC registration confirmed"
                        )
                    else:
                        print(
                            "[SIGNALING] PC registration code mismatch"
                        )

                    continue

                if self._handler:
                    try:
                        await self._handler(message)
                    except Exception as e:
                        print(
                            "[SIGNALING] Message handler error:",
                            e,
                        )

        except asyncio.CancelledError:
            raise

        except Exception as e:
            if not self._closing:
                print(
                    "[SIGNALING] Receive stopped:",
                    e,
                )

        finally:
            if self.ws is ws:
                self.ws = None
                self.connected = False

            if self._receive_task is asyncio.current_task():
                self._receive_task = None

            if not self._closing:
                if self.on_disconnect is not None:
                    try:
                        await self.on_disconnect()
                    except Exception as e:
                        print(
                            "[SIGNALING] Disconnect callback error:",
                            e,
                        )

                self._schedule_reconnect()

    def _schedule_reconnect(self):
        if self._closing:
            return

        if (
            self._reconnect_task is not None
            and not self._reconnect_task.done()
        ):
            return

        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop()
        )

    async def _reconnect_loop(self):
        delay = 1.0

        while (
            not self._closing
            and not self.connected
        ):
            print(
                f"[SIGNALING] Reconnect in "
                f"{delay:.0f}s..."
            )

            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

            if self._closing or self.connected:
                return

            try:
                await self._connect_once()

                if self.connected:
                    print(
                        "[SIGNALING] Reconnected"
                    )
                    return

            except asyncio.CancelledError:
                return

            except Exception as e:
                print(
                    "[SIGNALING] Reconnect failed:",
                    e,
                )

            delay = min(
                delay * 2.0,
                5.0,
            )

    async def send(
        self,
        payload: dict,
    ):
        ws = self.ws

        if (
            not self.connected
            or ws is None
        ):
            raise RuntimeError(
                "Signaling is not connected"
            )

        try:
            await ws.send(
                json.dumps(
                    payload,
                    separators=(",", ":"),
                )
            )

        except Exception:
            if self.ws is ws:
                self.connected = False

                try:
                    await ws.close()
                except Exception:
                    pass

            raise

    async def send_offer(
        self,
        sdp: str,
    ):
        await self.send({
            "type": "offer",
            "sdp": sdp,
        })

    async def send_answer(
        self,
        sdp: str,
    ):
        await self.send({
            "type": "answer",
            "sdp": sdp,
        })

    async def send_candidate(
        self,
        candidate,
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
            payload["sdpMLineIndex"] = (
                candidate.sdpMLineIndex
            )

        await self.send(payload)

    async def close(self):
        self._closing = True
        self.connected = False

        if self._reconnect_task is not None:
            if not self._reconnect_task.done():
                self._reconnect_task.cancel()

            self._reconnect_task = None

        if self._receive_task is not None:
            if not self._receive_task.done():
                self._receive_task.cancel()

            self._receive_task = None

        ws = self.ws
        self.ws = None

        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
