from __future__ import annotations

import base64
import hashlib
import secrets
import time
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from core.security.identity import WindowsIdentity


AUTH_VERSION = 1
AUTH_ALGORITHM = "ECDSA-P256-IDENTITY-V1"

CHALLENGE_SIZE = 32
CHALLENGE_TTL_SECONDS = 15.0


class ConnectionAuth:
    """
    Authentication for ordinary LazyPC connections.

    This is intentionally separate from Trusted Device authentication.

    Ordinary connection:
        PC ID
            ↓
        signaling
            ↓
        WebRTC
            ↓
        identity challenge
            ↓
        Android Identity Key proves ownership
            ↓
        user approval
            ↓
        session authorization
    """

    def __init__(
        self,
        identity: WindowsIdentity | None = None,
    ) -> None:

        self.identity = identity or WindowsIdentity()
        self.identity.ensure_created()

        self._connection_id: str | None = None
        self._challenge: bytes | None = None
        self._created_at: float | None = None

        self._remote_identity_public: str | None = None
        self._remote_device_id: str | None = None

    # ================================================================
    # SESSION
    # ================================================================

    @property
    def connection_id(self) -> str | None:
        return self._connection_id

    @property
    def remote_identity_public(self) -> str | None:
        return self._remote_identity_public

    @property
    def remote_device_id(self) -> str | None:
        return self._remote_device_id

    def create_session(self) -> dict:
        """
        Create a completely new ordinary connection session.

        Every connection gets:
            - a new connection_id
            - a new random challenge

        Nothing from a previous session is reused.
        """

        self.clear()

        self._connection_id = str(uuid.uuid4())
        self._challenge = secrets.token_bytes(CHALLENGE_SIZE)
        self._created_at = time.monotonic()

        challenge_b64 = base64.b64encode(
            self._challenge
        ).decode("ascii")

        return {
            "type": "connection_auth_challenge",
            "version": AUTH_VERSION,
            "algorithm": AUTH_ALGORITHM,
            "connection_id": self._connection_id,
            "challenge": challenge_b64,
            "pc_identity_public": (
                self.identity.identity_public_key_b64()
            ),
        }

    # ================================================================
    # CHALLENGE
    # ================================================================

    def _get_challenge(self) -> bytes:
        if self._challenge is None:
            raise RuntimeError(
                "No ordinary connection authentication is pending."
            )

        if self._created_at is None:
            raise RuntimeError(
                "Authentication challenge timestamp is missing."
            )

        if (
            time.monotonic() - self._created_at
            > CHALLENGE_TTL_SECONDS
        ):
            self.clear()

            raise RuntimeError(
                "Authentication challenge expired."
            )

        return self._challenge

    # ================================================================
    # TRANSCRIPT
    # ================================================================

    def _authentication_transcript(
        self,
        identity_public: str,
    ) -> bytes:

        if self._connection_id is None:
            raise RuntimeError(
                "No connection session is active."
            )

        challenge = self._get_challenge()

        challenge_b64 = base64.b64encode(
            challenge
        ).decode("ascii")

        pc_identity_public = (
            self.identity.identity_public_key_b64()
        )

        return (
            "LAZYPC_CONNECTION_AUTH_V1|"
            f"{self._connection_id}|"
            f"{pc_identity_public}|"
            f"{identity_public}|"
            f"{challenge_b64}"
        ).encode("utf-8")

    # ================================================================
    # PUBLIC KEY
    # ================================================================

    @staticmethod
    def _load_public_key(
        value: str,
    ) -> ec.EllipticCurvePublicKey:

        try:
            key = serialization.load_der_public_key(
                base64.b64decode(
                    value,
                    validate=True,
                )
            )
        except Exception as error:
            raise RuntimeError(
                "Invalid Android identity public key."
            ) from error

        if not isinstance(
            key,
            ec.EllipticCurvePublicKey,
        ):
            raise RuntimeError(
                "Android identity key is not EC."
            )

        if not isinstance(
            key.curve,
            ec.SECP256R1,
        ):
            raise RuntimeError(
                "Android identity key is not P-256."
            )

        return key

    # ================================================================
    # VERIFY
    # ================================================================

    def verify_response(
        self,
        response: dict,
    ) -> dict:

        self._get_challenge()

        if response.get("type") != "connection_auth_response":
            raise RuntimeError(
                "Unexpected ordinary authentication message."
            )

        if response.get("version") != AUTH_VERSION:
            raise RuntimeError(
                "Unsupported ordinary authentication version."
            )

        if response.get("algorithm") != AUTH_ALGORITHM:
            raise RuntimeError(
                "Unsupported ordinary authentication algorithm."
            )

        connection_id = response.get("connection_id")

        if (
            not connection_id
            or connection_id != self._connection_id
        ):
            self.clear()

            raise RuntimeError(
                "Connection ID mismatch."
            )

        identity_public = response.get(
            "identity_public"
        )

        signature_b64 = response.get(
            "identity_signature"
        )

        device_id = response.get(
            "device_id"
        )

        if not identity_public:
            self.clear()

            raise RuntimeError(
                "Missing Android identity public key."
            )

        if not signature_b64:
            self.clear()

            raise RuntimeError(
                "Missing Android identity signature."
            )

        # ------------------------------------------------------------
        # Verify signature
        # ------------------------------------------------------------

        public_key = self._load_public_key(
            identity_public
        )

        transcript = self._authentication_transcript(
            identity_public
        )

        try:
            signature = base64.b64decode(
                signature_b64,
                validate=True,
            )

            public_key.verify(
                signature,
                transcript,
                ec.ECDSA(hashes.SHA256()),
            )

        except Exception as error:
            self.clear()

            raise RuntimeError(
                "Android identity signature is invalid."
            ) from error

        # ------------------------------------------------------------
        # Derive a stable device identifier from Identity Key
        #
        # The supplied device_id is informational for now.
        # The cryptographic identity remains the public key itself.
        # ------------------------------------------------------------

        identity_der = base64.b64decode(
            identity_public,
            validate=True,
        )

        digest = hashlib.sha256(
            identity_der
        ).digest()

        derived_device_id = (
            "android-"
            + base64.urlsafe_b64encode(
                digest
            )
            .rstrip(b"=")
            .decode("ascii")[:22]
        )

        if device_id and device_id != derived_device_id:
            self.clear()

            raise RuntimeError(
                "Android device ID does not match identity key."
            )

        self._remote_identity_public = (
            identity_public
        )

        self._remote_device_id = (
            derived_device_id
        )

        # Challenge becomes single-use immediately after
        # successful authentication.
        self._challenge = None
        self._created_at = None

        return {
            "connection_id": connection_id,
            "identity_public": identity_public,
            "device_id": derived_device_id,
        }

    # ================================================================
    # SERVER AUTHENTICATION
    # ================================================================

    def server_authentication_message(self) -> dict:
        """
        Build the Windows -> Android authentication proof.

        Android will verify this using pc_identity_public.

        This gives us mutual authentication once the Android side
        implements the corresponding verification.
        """

        if not self._connection_id:
            raise RuntimeError(
                "No connection session is active."
            )

        if not self._remote_identity_public:
            raise RuntimeError(
                "Remote identity has not been authenticated."
            )

        transcript = (
            "LAZYPC_CONNECTION_AUTH_V1|SERVER|"
            f"{self._connection_id}|"
            f"{self.identity.identity_public_key_b64()}|"
            f"{self._remote_identity_public}"
        ).encode("utf-8")

        signature = self.identity.sign_identity(
            transcript
        )

        return {
            "type": "connection_auth_complete",
            "version": AUTH_VERSION,
            "algorithm": AUTH_ALGORITHM,
            "connection_id": self._connection_id,
            "pc_identity_public": (
                self.identity.identity_public_key_b64()
            ),
            "pc_identity_signature": (
                base64.b64encode(signature)
                .decode("ascii")
            ),
        }

    # ================================================================
    # CLEAR
    # ================================================================

    def clear(self) -> None:
        self._connection_id = None
        self._challenge = None
        self._created_at = None

        self._remote_identity_public = None
        self._remote_device_id = None