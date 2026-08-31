from __future__ import annotations

import secrets
import time

from .protocol import (
    AUTH_SECRET_MAX,
    AUTH_SECRET_MIN,
    AUTH_SECRET_TTL_SECONDS,
    MAX_AUTH_ATTEMPTS,
)


class OneTimeSecret:
    """
    One-time 9-digit authentication secret.

    The secret is generated locally on Windows and must never be
    transmitted through signaling.

    It is:
        - cryptographically random;
        - short-lived;
        - limited to a fixed number of attempts;
        - consumed after successful verification;
        - destroyed when the session ends.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = AUTH_SECRET_TTL_SECONDS,
        max_attempts: int = MAX_AUTH_ATTEMPTS,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(
                "Secret TTL must be positive."
            )

        if max_attempts <= 0:
            raise ValueError(
                "Maximum attempts must be positive."
            )

        self._ttl_seconds = ttl_seconds
        self._max_attempts = max_attempts

        self._value: str | None = None
        self._created_at: float | None = None

        self._attempts = 0
        self._consumed = False

    # ================================================================
    # PROPERTIES
    # ================================================================

    @property
    def attempts(self) -> int:
        return self._attempts

    @property
    def remaining_attempts(self) -> int:
        return max(
            0,
            self._max_attempts - self._attempts,
        )

    @property
    def consumed(self) -> bool:
        return self._consumed

    @property
    def expired(self) -> bool:
        if self._value is None:
            return True

        if self._created_at is None:
            return True

        return (
            time.monotonic() - self._created_at
            >= self._ttl_seconds
        )

    @property
    def available(self) -> bool:
        return (
            self._value is not None
            and not self._consumed
            and not self.expired
            and self._attempts < self._max_attempts
        )

    # ================================================================
    # GENERATION
    # ================================================================

    def generate(self) -> str:
        """
        Generate a fresh 9-digit secret.

        Any previous secret is destroyed first.
        """

        self.clear()

        value = secrets.randbelow(
            AUTH_SECRET_MAX - AUTH_SECRET_MIN + 1
        ) + AUTH_SECRET_MIN

        self._value = str(value)
        self._created_at = time.monotonic()

        return self._value

    # ================================================================
    # VALUE
    # ================================================================

    def get_value(self) -> str:
        """
        Return the current secret.

        This method is intended only for trusted local Windows UI.

        It must never be called by signaling or network serialization
        code.
        """

        if not self.available:
            raise RuntimeError(
                "Authentication secret is no longer available."
            )

        if self._value is None:
            raise RuntimeError(
                "Authentication secret does not exist."
            )

        return self._value

    # ================================================================
    # VERIFICATION
    # ================================================================

    def verify_format(
        self,
        supplied: str,
    ) -> bool:
        """
        Validate the format of a supplied secret.

        This does not compare the secret value and does not consume
        an authentication attempt.
        """

        return (
            isinstance(supplied, str)
            and len(supplied) == 9
            and supplied.isdigit()
        )

    # ================================================================
    # FAILED ATTEMPT
    # ================================================================

    def register_failure(self) -> int:
        """
        Register one failed authentication attempt.

        Returns the number of remaining attempts.
        """

        if not self.available:
            return 0

        self._attempts += 1

        return self.remaining_attempts

    # ================================================================
    # CONSUME
    # ================================================================

    def consume(self) -> None:
        """
        Consume the secret permanently.
        """

        if not self.available:
            return

        self._consumed = True
        self._value = None
        self._created_at = None

    # ================================================================
    # CLEAR
    # ================================================================

    def clear(self) -> None:
        """
        Destroy all secret state.
        """

        self._value = None
        self._created_at = None
        self._attempts = 0
        self._consumed = False