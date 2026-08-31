from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class SessionKeyDerivation:
    """
    Derive Ordinary V2 session keys from an ephemeral ECDH
    shared secret.

    Identity keys are deliberately not used as key material here.

    ECDH shared secret
        ↓
      HKDF
        ↓
    session key
    confirmation key
    """

    HASH_ALGORITHM = hashes.SHA256()

    # Domain separation.
    INFO_SESSION = b"LazyPC/OrdinaryV2/session"
    INFO_CONFIRMATION = b"LazyPC/OrdinaryV2/key-confirmation"

    KEY_SIZE = 32

    def __init__(
        self,
        *,
        session_id: str,
        transcript_hash: bytes,
    ) -> None:
        if not session_id:
            raise ValueError(
                "Session ID must not be empty."
            )

        if not isinstance(transcript_hash, bytes):
            raise TypeError(
                "Transcript hash must be bytes."
            )

        if len(transcript_hash) != hashlib.sha256().digest_size:
            raise ValueError(
                "Transcript hash must be a SHA-256 digest."
            )

        self._session_id = session_id
        self._transcript_hash = transcript_hash

    # ================================================================
    # DERIVE
    # ================================================================

    def derive(
        self,
        shared_secret: bytes,
    ) -> tuple[bytes, bytes]:
        """
        Derive:

            session_key
            confirmation_key

        from the ephemeral ECDH shared secret.

        The transcript hash is supplied as HKDF salt so that the
        resulting session keys are bound to this exact handshake.
        """

        if not isinstance(shared_secret, bytes):
            raise TypeError(
                "Shared secret must be bytes."
            )

        if not shared_secret:
            raise ValueError(
                "Shared secret must not be empty."
            )

        session_key = self._derive_key(
            shared_secret,
            self.INFO_SESSION,
        )

        confirmation_key = self._derive_key(
            shared_secret,
            self.INFO_CONFIRMATION,
        )

        return (
            session_key,
            confirmation_key,
        )

    # ================================================================
    # INTERNAL HKDF
    # ================================================================

    def _derive_key(
        self,
        shared_secret: bytes,
        info: bytes,
    ) -> bytes:
        """
        Perform one HKDF-SHA256 derivation.

        The session ID is included in the HKDF info to provide
        additional domain separation between sessions.
        """

        hkdf_info = (
            info
            + b"|"
            + self._session_id.encode("utf-8")
        )

        hkdf = HKDF(
            algorithm=self.HASH_ALGORITHM,
            length=self.KEY_SIZE,
            salt=self._transcript_hash,
            info=hkdf_info,
        )

        return hkdf.derive(shared_secret)