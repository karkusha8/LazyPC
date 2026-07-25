from __future__ import annotations

from typing import Optional

from fastapi import WebSocket


async def safe_send_text(ws: Optional[WebSocket], text: str) -> bool:
    if ws is None:
        return False

    try:
        await ws.send_text(text)
        return True
    except Exception as e:
        print("❌ SEND TEXT ERROR:", e)
        return False


async def safe_send_bytes(ws: Optional[WebSocket], data: bytes) -> bool:
    if ws is None:
        return False

    try:
        await ws.send_bytes(data)
        return True
    except Exception as e:
        print("❌ SEND BYTES ERROR:", e)
        return False


async def safe_close(ws: Optional[WebSocket]) -> None:
    if ws is None:
        return

    try:
        await ws.close()
    except Exception as e:
        print("❌ CLOSE ERROR:", e)