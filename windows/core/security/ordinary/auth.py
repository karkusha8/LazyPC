from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.security.common.identity import WindowsIdentity

from .key_confirmation import KeyConfirmation
from .key_derivation import SessionKeyDerivation
from .key_exchange import EphemeralKeyExchange
from .protocol import (
    AUTH_SECRET_TTL_SECONDS,
    CONFIRMATION_ALGORITHM,
    IDENTITY_ALGORITHM,
    KEY_EXCHANGE_ALGORITHM,
    KDF_ALGORITHM,
    MAX_AUTH_ATTEMPTS,
    MSG_AUTH_CHALLENGE,
    MSG_AUTH_COMPLETE,
    MSG_AUTH_SERVER_PROOF,
    MSG_KEY_CONFIRMATION,
    STATE_AUTHENTICATED,
    STATE_CLIENT_PROOF_VERIFIED,
    STATE_KEYS_DERIVED,
    STATE_REJECTED,
    STATE_WAITING_FOR_CLIENT,
    STATE_WAITING_FOR_CONFIRMATION,
)
from .replay import ReplayProtection
from .secret import OneTimeSecret
from .session import OrdinarySession
from .transcript import TranscriptBuilder


class OrdinaryAuthenticator:
    """
    Windows-side Ordinary V2 authentication engine.

    This class is deliberately independent from signaling,
    IPC, UI and WebRTC.

    Authentication consists of:

        PC ID lookup
            ↓
        fresh session
            ↓
        fresh 9-digit local secret
            ↓
        ephemeral ECDH
            ↓
        identity proof
            +
        knowledge of one-time secret
            ↓
        HKDF
            ↓
        key confirmation
            ↓
        authenticated session
    """

    CLIENT_IDENTITY_DOMAIN = (
        b"LazyPC/OrdinaryV2/client-identity-proof"
    )

    SERVER_IDENTITY_DOMAIN = (
        b"LazyPC/OrdinaryV2/server-identity-proof"
    )

    SECRET_KEY_DOMAIN = (
        b"LazyPC/OrdinaryV2/secret-key"
    )

    SECRET_PROOF_DOMAIN = (
        b"LazyPC/OrdinaryV2/secret-proof"
    )

    def __init__(
        self,
        identity: WindowsIdentity | None = None,
    ) -> None:
        self.identity = identity or WindowsIdentity()
        self.identity.ensure_created()

        self.session: OrdinarySession | None = None
        self.secret: OneTimeSecret | None = None

        self._replay = ReplayProtection()

        self._pc_id: str | None = None

    # ================================================================
    # SESSION CREATION
    # ================================================================

    def create_session(
        self,
    ) -> dict[str, Any]:
        """
        Create a fresh ordinary authentication session.

        The returned object is safe for signaling.

        The 9-digit secret is deliberately NOT included.
        """

        self.clear()

        pc_id = self.identity.device_id()

        session = OrdinarySession()

        key_exchange = EphemeralKeyExchange()
        key_exchange.generate()

        session.ephemeral_key_exchange = key_exchange

        secret = OneTimeSecret()
        secret.generate()

        self.session = session
        self.secret = secret
        self._pc_id = pc_id

        session.state = STATE_WAITING_FOR_CLIENT

        return {
            "type": MSG_AUTH_CHALLENGE,
            "version": 2,
            "pc_id": pc_id,
            "session_id": session.session_id,
            "nonce": self._b64(session.nonce),
            "pc_identity_public": (
                self.identity.identity_public_key_b64()
            ),
            "pc_ephemeral_public": (
                self._b64(key_exchange.public_key)
            ),
            "algorithms": {
                "identity": IDENTITY_ALGORITHM,
                "key_exchange": KEY_EXCHANGE_ALGORITHM,
                "kdf": KDF_ALGORITHM,
                "confirmation": CONFIRMATION_ALGORITHM,
            },
        }

    # ================================================================
    # LOCAL SECRET
    # ================================================================

    def get_display_secret(self) -> str:
        """
        Return the one-time secret for local Windows UI.

        This value must NEVER be serialized into signaling.
        """

        if self.secret is None:
            raise RuntimeError(
                "No ordinary authentication session exists."
            )

        return self.secret.get_value()

    # ================================================================
    # CLIENT RESPONSE
    # ================================================================

    def verify_client_response(
        self,
        response: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Verify the Android side of the Ordinary V2 handshake.
        """

        session = self._require_session()
        secret = self._require_secret()

        self._ensure_alive()

        if session.state != STATE_WAITING_FOR_CLIENT:
            raise RuntimeError(
                "Unexpected ordinary authentication state."
            )

        session_id = response.get("session_id")

        if session_id != session.session_id:
            self._reject("Session ID mismatch.")

        if self._replay.is_replayed(session.session_id):
            self._reject(
                "Ordinary session has already been consumed."
            )

        pc_id = response.get("pc_id")

        if pc_id != self._pc_id:
            self._reject("PC ID mismatch.")

        android_identity_public = response.get(
            "android_identity_public"
        )

        android_ephemeral_public = response.get(
            "android_ephemeral_public"
        )

        encrypted_proof = response.get(
            "encrypted_proof"
        )

        if not isinstance(
            android_identity_public,
            str,
        ):
            self._reject(
                "Missing Android identity public key."
            )

        if not isinstance(
            android_ephemeral_public,
            str,
        ):
            self._reject(
                "Missing Android ephemeral public key."
            )

        if not isinstance(
            encrypted_proof,
            str,
        ):
            self._reject(
                "Missing encrypted authentication proof."
            )

        android_ephemeral_der = self._decode_b64(
            android_ephemeral_public,
            "Invalid Android ephemeral public key.",
        )

        # ------------------------------------------------------------
        # Validate Android ephemeral public key.
        # ------------------------------------------------------------

        self._validate_ephemeral_public_key(
            android_ephemeral_der
        )

        # ------------------------------------------------------------
        # Derive ephemeral shared secret.
        # ------------------------------------------------------------

        key_exchange = session.ephemeral_key_exchange

        if key_exchange is None:
            self._reject(
                "Windows ephemeral key exchange is unavailable."
            )

        shared_secret = key_exchange.derive_shared_secret(
            android_ephemeral_der
        )

        session.android_ephemeral_public = (
            android_ephemeral_der
        )

        session.shared_secret = shared_secret

        # ------------------------------------------------------------
        # Build transcript.
        # ------------------------------------------------------------

        transcript = self._build_transcript(
            android_identity_public=android_identity_public,
            android_ephemeral_public=android_ephemeral_der,
        )

        transcript_hash = hashlib.sha256(
            transcript
        ).digest()

        # ------------------------------------------------------------
        # Derive secret-bound proof key.
        #
        # IMPORTANT:
        #
        # The 9-digit secret is combined with the ephemeral ECDH
        # shared secret before the proof is checked.
        #
        # Therefore an observer cannot simply capture an HMAC and
        # brute-force the 9-digit secret offline.
        # ------------------------------------------------------------

        secret_value = secret.get_value()

        proof_key = self._derive_secret_proof_key(
            shared_secret=shared_secret,
            secret_value=secret_value,
            transcript_hash=transcript_hash,
        )

        proof_plaintext = self._decrypt_client_proof(
            encrypted_proof=encrypted_proof,
            proof_key=proof_key,
            transcript_hash=transcript_hash,
        )

        # ------------------------------------------------------------
        # Verify identity proof.
        # ------------------------------------------------------------

        signature = proof_plaintext.get(
            "identity_signature"
        )

        if not isinstance(signature, str):
            self._register_failure(
                "Missing Android identity signature."
            )

        signature_bytes = self._decode_b64(
            signature,
            "Invalid Android identity signature.",
        )

        android_public_key = (
            self._load_identity_public_key(
                android_identity_public
            )
        )

        identity_payload = (
            self.CLIENT_IDENTITY_DOMAIN
            + b"|"
            + transcript_hash
        )

        try:
            android_public_key.verify(
                signature_bytes,
                identity_payload,
                ec.ECDSA(hashes.SHA256()),
            )
        except Exception as error:
            self._register_failure(
                "Android identity proof is invalid."
            )
            raise AssertionError from error

        # ------------------------------------------------------------
        # Verify secret proof.
        # ------------------------------------------------------------

        secret_proof = proof_plaintext.get(
            "secret_proof"
        )

        if not isinstance(secret_proof, str):
            self._register_failure(
                "Missing one-time secret proof."
            )

        expected_secret_proof = self._create_secret_proof(
            proof_key=proof_key,
            transcript_hash=transcript_hash,
        )

        if not hmac.compare_digest(
            expected_secret_proof,
            secret_proof,
        ):
            self._register_failure(
                "One-time authentication secret is invalid."
            )

        session.android_identity_public = (
            android_identity_public
        )

        session.client_identity_verified = True
        session.client_secret_verified = True

        session.state = STATE_CLIENT_PROOF_VERIFIED

        # ------------------------------------------------------------
        # Derive session keys.
        # ------------------------------------------------------------

        key_derivation = SessionKeyDerivation(
            session_id=session.session_id,
            transcript_hash=transcript_hash,
        )

        (
            session.session_key,
            session.confirmation_key,
        ) = key_derivation.derive(
            shared_secret
        )

        session.state = STATE_KEYS_DERIVED

        # The one-time secret is no longer needed after successful
        # client authentication.
        secret.consume()

        return {
            "session_id": session.session_id,
            "pc_id": self._require_pc_id(),
            "android_identity_public": (
                android_identity_public
            ),
            "android_ephemeral_public": (
                android_ephemeral_public
            ),
            "transcript_hash": self._b64(
                transcript_hash
            ),
        }

    # ================================================================
    # SERVER IDENTITY PROOF
    # ================================================================

    def build_server_proof(self) -> dict[str, Any]:
        """
        Build the Windows identity proof.
        """

        session = self._require_session()

        if session.state != STATE_KEYS_DERIVED:
            raise RuntimeError(
                "Session keys have not been derived."
            )

        transcript_hash = self._current_transcript_hash()

        payload = (
            self.SERVER_IDENTITY_DOMAIN
            + b"|"
            + transcript_hash
        )

        signature = self.identity.sign_identity(
            payload
        )

        session.server_identity_proven = True
        session.state = STATE_WAITING_FOR_CONFIRMATION

        return {
            "type": MSG_AUTH_SERVER_PROOF,
            "version": 2,
            "session_id": session.session_id,
            "pc_id": self._require_pc_id(),
            "pc_identity_public": (
                self.identity.identity_public_key_b64()
            ),
            "pc_identity_signature": (
                self._b64(signature)
            ),
            "pc_ephemeral_public": (
                self._b64(
                    self._require_session()
                    .ephemeral_key_exchange
                    .public_key
                )
            ),
        }

    # ================================================================
    # SERVER KEY CONFIRMATION
    # ================================================================

    def build_server_key_confirmation(
        self,
    ) -> dict[str, Any]:
        """
        Create Windows -> Android key confirmation.
        """

        session = self._require_session()

        if session.state != STATE_WAITING_FOR_CONFIRMATION:
            raise RuntimeError(
                "Session is not ready for key confirmation."
            )

        confirmation = (
            KeyConfirmation.create_server_confirmation(
                self._require_confirmation_key(),
                self._current_transcript_hash(),
            )
        )

        return {
            "type": MSG_KEY_CONFIRMATION,
            "version": 2,
            "direction": "server",
            "session_id": session.session_id,
            "confirmation": confirmation,
        }

    # ================================================================
    # CLIENT KEY CONFIRMATION
    # ================================================================

    def verify_client_key_confirmation(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Verify Android -> Windows key confirmation.

        Successful verification is the final authentication point.
        """

        session = self._require_session()

        if session.state != STATE_WAITING_FOR_CONFIRMATION:
            self._reject(
                "Unexpected key confirmation."
            )

        if message.get("type") != MSG_KEY_CONFIRMATION:
            self._reject(
                "Invalid key confirmation message."
            )

        if message.get("version") != 2:
            self._reject(
                "Unsupported key confirmation version."
            )

        if message.get("direction") != "client":
            self._reject(
                "Invalid key confirmation direction."
            )

        if message.get("session_id") != session.session_id:
            self._reject(
                "Key confirmation session mismatch."
            )

        confirmation = message.get(
            "confirmation"
        )

        if not isinstance(confirmation, str):
            self._reject(
                "Missing key confirmation."
            )

        valid = (
            KeyConfirmation.verify_client_confirmation(
                self._require_confirmation_key(),
                self._current_transcript_hash(),
                confirmation,
            )
        )

        if not valid:
            self._reject(
                "Client key confirmation failed."
            )

        session.key_confirmation_verified = True
        session.state = STATE_AUTHENTICATED

        self._replay.consume(
            session.session_id,
            ttl_seconds=AUTH_SECRET_TTL_SECONDS,
        )

        return {
            "type": MSG_AUTH_COMPLETE,
            "version": 2,
            "session_id": session.session_id,
            "authenticated": True,
        }

    # ================================================================
    # TRANSCRIPT
    # ================================================================

    def _build_transcript(
        self,
        *,
        android_identity_public: str,
        android_ephemeral_public: bytes,
    ) -> bytes:
        session = self._require_session()
        key_exchange = session.ephemeral_key_exchange

        if key_exchange is None:
            raise RuntimeError(
                "Windows ephemeral key exchange is unavailable."
            )

        return (
            TranscriptBuilder()
            .add_text(
                "protocol_version",
                "2",
            )
            .add_text(
                "session_id",
                session.session_id,
            )
            .add_text(
                "pc_id",
                self._require_pc_id(),
            )
            .add_text(
                "windows_identity_public",
                self.identity.identity_public_key_b64(),
            )
            .add_text(
                "android_identity_public",
                android_identity_public,
            )
            .add_bytes(
                "windows_ephemeral_public",
                key_exchange.public_key,
            )
            .add_bytes(
                "android_ephemeral_public",
                android_ephemeral_public,
            )
            .add_bytes(
                "nonce",
                session.nonce,
            )
            .build()
        )

    # ================================================================
    # SECRET-BOUND PROOF KEY
    # ================================================================

    def _derive_secret_proof_key(
        self,
        *,
        shared_secret: bytes,
        secret_value: str,
        transcript_hash: bytes,
    ) -> bytes:
        """
        Derive a proof key from BOTH:

            ephemeral ECDH secret
            +
            one-time 9-digit secret

        The resulting key is bound to the exact transcript.
        """

        secret_material = (
            self.SECRET_KEY_DOMAIN
            + b"|"
            + secret_value.encode("ascii")
        )

        secret_hash = hashlib.sha256(
            secret_material
        ).digest()

        derivation_input = (
            shared_secret
            + secret_hash
        )

        return hashlib.sha256(
            derivation_input
            + transcript_hash
        ).digest()

    # ================================================================
    # SECRET PROOF
    # ================================================================

    @classmethod
    def _create_secret_proof(
        cls,
        *,
        proof_key: bytes,
        transcript_hash: bytes,
    ) -> str:
        message = (
            cls.SECRET_PROOF_DOMAIN
            + b"|"
            + transcript_hash
        )

        proof = hmac.new(
            proof_key,
            message,
            hashlib.sha256,
        ).digest()

        return base64.b64encode(
            proof
        ).decode("ascii")

    # ================================================================
    # CLIENT PROOF DECRYPTION
    # ================================================================

    def _decrypt_client_proof(
        self,
        *,
        encrypted_proof: str,
        proof_key: bytes,
        transcript_hash: bytes,
    ) -> dict[str, Any]:
        """
        Decrypt the Android proof.

        AES-GCM provides authenticated encryption and binds the
        ciphertext to the exact transcript through AAD.
        """

        encoded = self._decode_b64(
            encrypted_proof,
            "Invalid encrypted authentication proof.",
        )

        if len(encoded) < 12 + 16:
            self._register_failure(
                "Encrypted authentication proof is invalid."
            )

        nonce = encoded[:12]
        ciphertext = encoded[12:]

        aad = (
            b"LazyPC/OrdinaryV2/client-proof"
            + b"|"
            + transcript_hash
        )

        try:
            plaintext = AESGCM(
                proof_key
            ).decrypt(
                nonce,
                ciphertext,
                aad,
            )
        except Exception as error:
            self._register_failure(
                "Authentication proof could not be verified."
            )
            raise AssertionError from error

        try:
            import json

            value = json.loads(
                plaintext.decode("utf-8")
            )
        except Exception as error:
            self._register_failure(
                "Authentication proof format is invalid."
            )
            raise AssertionError from error

        if not isinstance(value, dict):
            self._register_failure(
                "Authentication proof must be an object."
            )

        return value

    # ================================================================
    # IDENTITY PUBLIC KEY
    # ================================================================

    @staticmethod
    def _load_identity_public_key(
        value: str,
    ) -> ec.EllipticCurvePublicKey:
        try:
            encoded = base64.b64decode(
                value,
                validate=True,
            )

            key = serialization.load_der_public_key(
                encoded
            )
        except Exception as error:
            raise RuntimeError(
                "Invalid identity public key."
            ) from error

        if not isinstance(
            key,
            ec.EllipticCurvePublicKey,
        ):
            raise RuntimeError(
                "Identity public key is not an EC key."
            )

        if not isinstance(
            key.curve,
            ec.SECP256R1,
        ):
            raise RuntimeError(
                "Identity public key is not P-256."
            )

        return key

    # ================================================================
    # EPHEMERAL PUBLIC KEY
    # ================================================================

    @staticmethod
    def _validate_ephemeral_public_key(
        value: bytes,
    ) -> None:
        try:
            key = serialization.load_der_public_key(
                value
            )
        except Exception as error:
            raise RuntimeError(
                "Invalid ephemeral public key."
            ) from error

        if not isinstance(
            key,
            ec.EllipticCurvePublicKey,
        ):
            raise RuntimeError(
                "Ephemeral public key is not an EC key."
            )

        if not isinstance(
            key.curve,
            ec.SECP256R1,
        ):
            raise RuntimeError(
                "Ephemeral public key is not P-256."
            )

    # ================================================================
    # HELPERS
    # ================================================================

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.b64encode(
            value
        ).decode("ascii")

    @staticmethod
    def _decode_b64(
        value: str,
        error_message: str,
    ) -> bytes:
        try:
            return base64.b64decode(
                value,
                validate=True,
            )
        except Exception as error:
            raise RuntimeError(
                error_message
            ) from error

    def _current_transcript_hash(self) -> bytes:
        session = self._require_session()

        if session.android_identity_public is None:
            raise RuntimeError(
                "Android identity is unavailable."
            )

        if session.android_ephemeral_public is None:
            raise RuntimeError(
                "Android ephemeral key is unavailable."
            )

        transcript = self._build_transcript(
            android_identity_public=(
                session.android_identity_public
            ),
            android_ephemeral_public=(
                session.android_ephemeral_public
            ),
        )

        return hashlib.sha256(
            transcript
        ).digest()

    def _require_session(self) -> OrdinarySession:
        if self.session is None:
            raise RuntimeError(
                "No ordinary authentication session exists."
            )

        return self.session

    def _require_secret(self) -> OneTimeSecret:
        if self.secret is None:
            raise RuntimeError(
                "No ordinary authentication secret exists."
            )

        return self.secret

    def _require_confirmation_key(self) -> bytes:
        value = self._require_session().confirmation_key

        if value is None:
            raise RuntimeError(
                "Confirmation key is unavailable."
            )

        return value

    def _require_pc_id(self) -> str:
        if self._pc_id is None:
            raise RuntimeError(
                "PC ID is unavailable."
            )

        return self._pc_id

    def _ensure_alive(self) -> None:
        session = self._require_session()

        if session.is_expired():
            session.state = STATE_REJECTED
            self.clear()

            raise RuntimeError(
                "Ordinary authentication session expired."
            )

    def _register_failure(
        self,
        reason: str,
    ) -> None:
        session = self._require_session()

        # We use the OneTimeSecret attempt counter as the primary
        # per-session authentication limiter.
        secret = self._require_secret()

        secret._attempts += 1

        remaining = secret.remaining_attempts

        if remaining <= 0:
            session.state = STATE_REJECTED

            self.clear()

            raise RuntimeError(
                reason
                + " Maximum authentication attempts exceeded."
            )

        raise RuntimeError(
            reason
            + f" Remaining attempts: {remaining}."
        )

    def _reject(
        self,
        reason: str,
    ) -> None:
        if self.session is not None:
            self.session.state = STATE_REJECTED

        raise RuntimeError(reason)

    # ================================================================
    # STATE
    # ================================================================

    @property
    def authenticated(self) -> bool:
        return (
            self.session is not None
            and self.session.state == STATE_AUTHENTICATED
        )

    # ================================================================
    # CLEAR
    # ================================================================

    def clear(self) -> None:
        if self.session is not None:
            self.session.close()

        if self.secret is not None:
            self.secret.clear()

        self.session = None
        self.secret = None
        self._pc_id = None