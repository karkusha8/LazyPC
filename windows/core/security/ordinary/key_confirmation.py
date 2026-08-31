from __future__ import annotations

import base64
import hmac
import hashlib


class KeyConfirmation:
    """
    Key confirmation for Ordinary V2.

    Both sides derive the same confirmation key from the ephemeral
    ECDH shared secret.

    Windows creates a confirmation MAC.
    Android verifies it.

    The confirmation is bound to the exact transcript, so a valid
    confirmation from another session cannot be reused.
    """

    ALGORITHM = "HMAC-SHA256"

    DOMAIN_CLIENT = b"LazyPC/OrdinaryV2/key-confirmation/client"
    DOMAIN_SERVER = b"LazyPC/OrdinaryV2/key-confirmation/server"

    # ================================================================
    # SERVER CONFIRMATION
    # ================================================================

    @classmethod
    def create_server_confirmation(
        cls,
        confirmation_key: bytes,
        transcript_hash: bytes,
    ) -> str:
        """
        Create Windows -> Android key confirmation.

        The returned value is Base64 encoded for transport through
        signaling.
        """

        payload = cls._build_payload(
            cls.DOMAIN_SERVER,
            transcript_hash,
        )

        mac = hmac.new(
            confirmation_key,
            payload,
            hashlib.sha256,
        ).digest()

        return base64.b64encode(mac).decode("ascii")

    # ================================================================
    # VERIFY SERVER CONFIRMATION
    # ================================================================

    @classmethod
    def verify_server_confirmation(
        cls,
        confirmation_key: bytes,
        transcript_hash: bytes,
        confirmation_b64: str,
    ) -> bool:
        """
        Verify Windows -> Android key confirmation.
        """

        expected = cls.create_server_confirmation(
            confirmation_key,
            transcript_hash,
        )

        try:
            return hmac.compare_digest(
                expected,
                confirmation_b64,
            )
        except Exception:
            return False

    # ================================================================
    # CLIENT CONFIRMATION
    # ================================================================

    @classmethod
    def create_client_confirmation(
        cls,
        confirmation_key: bytes,
        transcript_hash: bytes,
    ) -> str:
        """
        Create Android -> Windows key confirmation.

        This is intentionally different from the server confirmation
        through domain separation.
        """

        payload = cls._build_payload(
            cls.DOMAIN_CLIENT,
            transcript_hash,
        )

        mac = hmac.new(
            confirmation_key,
            payload,
            hashlib.sha256,
        ).digest()

        return base64.b64encode(mac).decode("ascii")

    # ================================================================
    # VERIFY CLIENT CONFIRMATION
    # ================================================================

    @classmethod
    def verify_client_confirmation(
        cls,
        confirmation_key: bytes,
        transcript_hash: bytes,
        confirmation_b64: str,
    ) -> bool:
        """
        Verify Android -> Windows key confirmation.
        """

        expected = cls.create_client_confirmation(
            confirmation_key,
            transcript_hash,
        )

        try:
            return hmac.compare_digest(
                expected,
                confirmation_b64,
            )
        except Exception:
            return False

    # ================================================================
    # PAYLOAD
    # ================================================================

    @staticmethod
    def _build_payload(
        domain: bytes,
        transcript_hash: bytes,
    ) -> bytes:
        if not isinstance(transcript_hash, bytes):
            raise TypeError(
                "Transcript hash must be bytes."
            )

        if len(transcript_hash) != hashlib.sha256().digest_size:
            raise ValueError(
                "Transcript hash must be a SHA-256 digest."
            )

        return (
            domain
            + b"|"
            + transcript_hash
        )