from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class ReplayEntry:
    """
    A single previously accepted handshake identifier.
    """

    expires_at: float


class ReplayProtection:
    """
    Prevent reuse of previously accepted Ordinary V2 sessions.

    A session ID is considered consumed once authentication reaches
    the point where accepting the same handshake again would be unsafe.

    Entries are temporary and automatically expire.
    """

    def __init__(self) -> None:
        self._entries: dict[str, ReplayEntry] = {}

    # ================================================================
    # CHECK
    # ================================================================

    def is_replayed(self, session_id: str) -> bool:
        """
        Return True if the session ID has already been consumed
        and has not yet expired.
        """

        if not isinstance(session_id, str) or not session_id:
            return True

        self._cleanup()

        return session_id in self._entries

    # ================================================================
    # CONSUME
    # ================================================================

    def consume(
        self,
        session_id: str,
        *,
        ttl_seconds: float,
    ) -> None:
        """
        Mark a session ID as consumed.

        A session ID must never be consumed twice.
        """

        if not isinstance(session_id, str) or not session_id:
            raise ValueError(
                "Session ID must not be empty."
            )

        if ttl_seconds <= 0:
            raise ValueError(
                "Replay entry TTL must be positive."
            )

        self._cleanup()

        if session_id in self._entries:
            raise RuntimeError(
                "Session ID has already been consumed."
            )

        self._entries[session_id] = ReplayEntry(
            expires_at=time.monotonic() + ttl_seconds
        )

    # ================================================================
    # CLEANUP
    # ================================================================

    def _cleanup(self) -> None:
        now = time.monotonic()

        expired = [
            session_id
            for session_id, entry in self._entries.items()
            if entry.expires_at <= now
        ]

        for session_id in expired:
            del self._entries[session_id]

    # ================================================================
    # CLEAR
    # ================================================================

    def clear(self) -> None:
        """
        Remove all replay-protection state.
        """

        self._entries.clear()