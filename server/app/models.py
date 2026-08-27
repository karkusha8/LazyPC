from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from fastapi import WebSocket


class PeerRole(str, Enum):
    CLIENT = "client"
    AGENT = "agent"


@dataclass
class AgentEntry:
    pc_id: str
    ws: WebSocket


@dataclass
class ClientEntry:
    ws: WebSocket
    pc_id: Optional[str] = None
    pairing_mode: bool = False
    connection_mode: Optional[str] = None


@dataclass
class SessionState:
    """
    Signaling-only routing state.

    pc_id is a public locator, not an authentication credential.
    Cryptographic authentication remains inside ConnectionAuth.
    """
    agents: dict[str, AgentEntry] = field(default_factory=dict)
    clients: dict[WebSocket, ClientEntry] = field(default_factory=dict)
