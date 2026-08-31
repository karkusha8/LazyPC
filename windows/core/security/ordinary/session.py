from __future__ import annotations

import secrets
import time
import uuid
from dataclasses import dataclass, field

from .key_exchange import EphemeralKeyExchange
from .protocol import (
    NONCE_SIZE,
    SESSION_TTL_SECONDS,
    STATE_CLOSED,
    STATE_CREATED,
    STATE_EXPIRED,
    STATE_REJECTED,
)


@dataclass
class OrdinarySession:
    """
    State of exactly one Ordinary V2 authentication session.

    This object contains protocol state only.

    It must never be serialized directly to signaling because
    it can contain sensitive private/session material.
    """

    session_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    created_at: float = field(
        default_factory=time.monotonic
    )

    ttl_seconds: float = SESSION_TTL_SECONDS

    state: str = STATE_CREATED

    # Fresh session nonce.
    nonce: bytes = field(
        default_factory=lambda: secrets.token_bytes(NONCE_SIZE)
    )

    # ------------------------------------------------------------
    # Remote identity
    # ------------------------------------------------------------

    android_identity_public: str | None = None
    android_device_id: str | None = None

    # ------------------------------------------------------------
    # Ephemeral ECDH
    # ------------------------------------------------------------

    ephemeral_key_exchange: EphemeralKeyExchange | None = None

    android_ephemeral_public: bytes | None = None

    # ------------------------------------------------------------
    # Derived session material
    # ------------------------------------------------------------

    shared_secret: bytes | None = None

    session_key: bytes | None = None
    confirmation_key: bytes | None = None

    # ------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------

    client_identity_verified: bool = False
    client_secret_verified: bool = False
    server_identity_proven: bool = False
    key_confirmation_verified: bool = False

    # ------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------

    def is_expired(self) -> bool:
        return (
            time.monotonic() - self.created_at
            >= self.ttl_seconds
        )

    def is_alive(self) -> bool:
        return (
            self.state not in {
                STATE_REJECTED,
                STATE_EXPIRED,
                STATE_CLOSED,
            }
            and not self.is_expired()
        )

    def clear_ephemeral_key_exchange(self) -> None:
        """
        Destroy the session's ephemeral key-exchange state.

        The ephemeral private key is never serialized or persisted.
        The cryptographic object is released by clearing the owner
        reference here.
        """

        if self.ephemeral_key_exchange is not None:
            self.ephemeral_key_exchange.clear()

        self.ephemeral_key_exchange = None

    def clear_secrets(self) -> None:
        """
        Remove sensitive derived session material.
        """

        self.shared_secret = None
        self.session_key = None
        self.confirmation_key = None

        self.clear_ephemeral_key_exchange()

    def close(self) -> None:
        """
        Permanently close this session and destroy sensitive material.
        """

        self.clear_secrets()

        self.android_identity_public = None
        self.android_device_id = None
        self.android_ephemeral_public = None

        self.state = STATE_CLOSED