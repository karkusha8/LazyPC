from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import asyncio
from typing import Optional

from fastapi import WebSocket


class PeerRole(str, Enum):
    CLIENT = "client"
    AGENT = "agent"


@dataclass
class SessionState:
    client_ws: Optional[WebSocket] = None
    agent_ws: Optional[WebSocket] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)