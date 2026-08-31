from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RateLimitState:
    """
    Authentication-attempt state for one ordinary connection.
    """

    attempts: int = 0
    locked: bool = False
    locked_until: float | None = None


class AuthenticationRateLimiter:
    """
    Strict authentication attempt limiter.

    Ordinary authentication allows at most three failed attempts
    for a session.

    Once the limit is reached, the current session is locked.
    """

    def __init__(
        self,
        *,
        max_attempts: int = 3,
        lockout_seconds: float = 60.0,
    ) -> None:
        if max_attempts <= 0:
            raise ValueError(
                "Maximum attempts must be positive."
            )

        if lockout_seconds <= 0:
            raise ValueError(
                "Lockout duration must be positive."
            )

        self._max_attempts = max_attempts
        self._lockout_seconds = lockout_seconds

        self._sessions: dict[str, RateLimitState] = {}

    # ================================================================
    # STATE
    # ================================================================

    def _get_state(
        self,
        session_id: str,
    ) -> RateLimitState:
        if not isinstance(session_id, str) or not session_id:
            raise ValueError(
                "Session ID must not be empty."
            )

        state = self._sessions.get(session_id)

        if state is None:
            state = RateLimitState()
            self._sessions[session_id] = state

        self._refresh_lock(state)

        return state

    # ================================================================
    # CAN ATTEMPT
    # ================================================================

    def can_attempt(
        self,
        session_id: str,
    ) -> bool:
        """
        Return whether another authentication attempt is allowed.
        """

        state = self._get_state(session_id)

        return not state.locked

    # ================================================================
    # FAILED ATTEMPT
    # ================================================================

    def register_failure(
        self,
        session_id: str,
    ) -> int:
        """
        Register a failed authentication attempt.

        Returns the number of remaining attempts.

        When the maximum is reached, the session becomes locked.
        """

        state = self._get_state(session_id)

        if state.locked:
            return 0

        state.attempts += 1

        remaining = max(
            0,
            self._max_attempts - state.attempts,
        )

        if state.attempts >= self._max_attempts:
            state.locked = True
            state.locked_until = (
                time.monotonic()
                + self._lockout_seconds
            )

            return 0

        return remaining

    # ================================================================
    # SUCCESS
    # ================================================================

    def register_success(
        self,
        session_id: str,
    ) -> None:
        """
        Authentication succeeded.

        The rate-limit state for the session is no longer needed.
        """

        self._sessions.pop(
            session_id,
            None,
        )

    # ================================================================
    # LOCK STATE
    # ================================================================

    def is_locked(
        self,
        session_id: str,
    ) -> bool:
        state = self._get_state(session_id)
        return state.locked

    # ================================================================
    # CLEANUP
    # ================================================================

    def remove(
        self,
        session_id: str,
    ) -> None:
        self._sessions.pop(
            session_id,
            None,
        )

    def clear(self) -> None:
        self._sessions.clear()

    # ================================================================
    # INTERNAL
    # ================================================================

    @staticmethod
    def _refresh_lock(
        state: RateLimitState,
    ) -> None:
        if not state.locked:
            return

        if state.locked_until is None:
            return

        if time.monotonic() >= state.locked_until:
            state.locked = False
            state.locked_until = None
            state.attempts = 0