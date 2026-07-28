from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from fastapi import WebSocket


class PeerRole(str, Enum):
    CLIENT = "client"
    AGENT = "agent"


@dataclass
class SessionState:
    """
    Состояние одной активной WebRTC-сессии.
    """

    client_ws: Optional[WebSocket] = None
    agent_ws: Optional[WebSocket] = None

    # Последний Offer от Windows Agent.
    # Если Android подключится позже,
    # сервер сразу отправит ему этот Offer.
    last_offer: Optional[str] = None

    # На будущее:
    # session_id: Optional[str] = None
    # created_at: float = 0
    # reconnect_counter: int = 0

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)