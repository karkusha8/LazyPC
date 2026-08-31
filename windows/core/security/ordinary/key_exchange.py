from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


class EphemeralKeyExchange:
    """
    Ephemeral ECDH key exchange for one Ordinary V2 session.

    The private key exists only for the lifetime of the session.
    It must never be serialized, logged, or sent through signaling.
    """

    CURVE = ec.SECP256R1()

    def __init__(self) -> None:
        self._private_key: ec.EllipticCurvePrivateKey | None = None
        self._public_key: bytes | None = None

    # ================================================================
    # GENERATION
    # ================================================================

    def generate(self) -> bytes:
        """
        Generate a fresh ephemeral P-256 key pair.

        Returns the DER/SPKI encoded public key.
        """

        self.clear()

        private_key = ec.generate_private_key(self.CURVE)
        public_key = private_key.public_key()

        public_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        self._private_key = private_key
        self._public_key = public_der

        return public_der

    # ================================================================
    # PUBLIC KEY
    # ================================================================

    @property
    def public_key(self) -> bytes:
        if self._public_key is None:
            raise RuntimeError(
                "Ephemeral key pair has not been generated."
            )

        return self._public_key

    # ================================================================
    # SHARED SECRET
    # ================================================================

    def derive_shared_secret(
        self,
        peer_public_der: bytes,
    ) -> bytes:
        """
        Derive the ECDH shared secret using the peer's
        ephemeral public key.

        The peer public key is never trusted by itself; the caller
        must authenticate it through the Ordinary V2 transcript.
        """

        if self._private_key is None:
            raise RuntimeError(
                "Ephemeral private key is not available."
            )

        try:
            peer_public_key = serialization.load_der_public_key(
                peer_public_der
            )
        except Exception as error:
            raise RuntimeError(
                "Invalid ephemeral public key."
            ) from error

        if not isinstance(
            peer_public_key,
            ec.EllipticCurvePublicKey,
        ):
            raise RuntimeError(
                "Ephemeral public key is not an EC key."
            )

        if not isinstance(
            peer_public_key.curve,
            ec.SECP256R1,
        ):
            raise RuntimeError(
                "Ephemeral public key is not P-256."
            )

        return self._private_key.exchange(
            ec.ECDH(),
            peer_public_key,
        )

    # ================================================================
    # CLEAR
    # ================================================================

    def clear(self) -> None:
        """
        Destroy references to the ephemeral key material.
        """

        self._private_key = None
        self._public_key = None