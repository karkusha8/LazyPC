import asyncio
import json
from typing import Awaitable, Callable, Optional

import websockets

MessageHandler = Callable[[dict], Awaitable[None]]


class SignalingClient:
    """
    Long-lived signaling transport for the Windows Agent.

    Signaling is independent from WebRTC: losing this WebSocket must not
    destroy the Agent or the current PeerConnection. The transport reconnects
    in the background so the Agent is ready for the next client/session.
    """

    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self.connected = False

        self._handler: Optional[MessageHandler] = None
        self.on_disconnect = None

        self._closing = False
        self._receive_task = None
        self._reconnect_task = None
        self._connect_lock = asyncio.Lock()

    def set_message_handler(self, handler: MessageHandler):
        self._handler = handler

    def set_disconnect_handler(self, handler):
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

            await ws.send("HELLO_AGENT")

            self._receive_task = asyncio.create_task(
                self._receive_loop(ws)
            )

            print("[SIGNALING] Connected")

    async def _receive_loop(self, ws):
        try:
            async for raw in ws:
                try:
                    message = json.loads(raw)
                except Exception as e:
                    print("[SIGNALING] Invalid JSON:", e)
                    continue

                if self._handler:
                    try:
                        await self._handler(message)
                    except Exception as e:
                        print("[SIGNALING] Message handler error:", e)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closing:
                print("[SIGNALING] Receive stopped:", e)
        finally:
            # Ignore callbacks from an old socket after a newer connection
            # has already been installed.
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
                        print("[SIGNALING] Disconnect callback error:", e)

                self._schedule_reconnect()

    def _schedule_reconnect(self):
        if self._closing:
            return

        if self._reconnect_task is not None and not self._reconnect_task.done():
            return

        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop()
        )

    async def _reconnect_loop(self):
        delay = 1.0

        while not self._closing and not self.connected:
            print(f"[SIGNALING] Reconnect in {delay:.0f}s...")

            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                return

            if self._closing or self.connected:
                return

            try:
                await self._connect_once()
                if self.connected:
                    print("[SIGNALING] Reconnected")
                    return
            except asyncio.CancelledError:
                return
            except Exception as e:
                print("[SIGNALING] Reconnect failed:", e)

            delay = min(delay * 2.0, 5.0)

    async def send(self, payload: dict):
        ws = self.ws

        if not self.connected or ws is None:
            raise RuntimeError("Signaling is not connected")

        try:
            await ws.send(json.dumps(payload))
        except Exception:
            # Let the receive loop own reconnect/lifecycle. Do not turn a
            # transient signaling failure into an Agent shutdown.
            if self.ws is ws:
                self.connected = False
                try:
                    await ws.close()
                except Exception:
                    pass
            raise

    async def send_offer(self, sdp: str):
        await self.send({
            "type": "offer",
            "sdp": sdp,
        })

    async def send_answer(self, sdp: str):
        await self.send({
            "type": "answer",
            "sdp": sdp,
        })

    async def send_candidate(self, candidate):
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