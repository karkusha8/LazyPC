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
    Current signaling session.

    client_pairing is routing metadata only. It is NOT an authentication
    decision and must never be treated as proof that a device is trusted.
    """
    client_ws: Optional[WebSocket] = None
    agent_ws: Optional[WebSocket] = None
    client_pairing: bool = False
    last_offer: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
