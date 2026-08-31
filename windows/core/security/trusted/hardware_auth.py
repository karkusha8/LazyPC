from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .attestation_verifier import AttestationError, verify_hardware_attestation


PROTOCOL_VERSION = 1
ALGORITHM = "ECDSA-P256-HW-ATTESTATION"
CHALLENGE_SIZE = 32
SESSION_ID_SIZE = 16
CHALLENGE_TTL_SECONDS = 15.0


class HardwareAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingHardwareSession:
    session_id: str
    challenge_b64: str
    created_at: float


class HardwareWebRTCAuthenticator:
    """
    Stage 3.

    The hardware public key is NOT learned/trusted from the current
    WebRTC response. It must already be registered for the authenticated
    Trusted Device.

    This class verifies:
      1. fresh challenge
      2. current Stage-3 session binding
      3. exact registered hardware public key
      4. Android hardware attestation
      5. hardware signature
    """

    def __init__(self, expected_hardware_public: str | None = None):
        self._pending: PendingHardwareSession | None = None
        self._expected_hardware_public = expected_hardware_public

    def set_expected_hardware_public(self, value: str | None) -> None:
        self._expected_hardware_public = value

    def begin(self) -> dict:
        if not self._expected_hardware_public:
            raise HardwareAuthError(
                "No registered hardware key for this Trusted Device"
            )

        challenge = secrets.token_bytes(CHALLENGE_SIZE)
        session_id = secrets.token_hex(SESSION_ID_SIZE)
        challenge_b64 = base64.b64encode(challenge).decode("ascii")

        self._pending = PendingHardwareSession(
            session_id=session_id,
            challenge_b64=challenge_b64,
            created_at=time.monotonic(),
        )

        return {
            "type": "hw_auth_challenge",
            "version": PROTOCOL_VERSION,
            "algorithm": ALGORITHM,
            "session_id": session_id,
            "challenge": challenge_b64,
        }

    def _get_pending(self) -> PendingHardwareSession:
        pending = self._pending

        if pending is None:
            raise HardwareAuthError(
                "No pending hardware authentication"
            )

        if time.monotonic() - pending.created_at > CHALLENGE_TTL_SECONDS:
            self._pending = None
            raise HardwareAuthError(
                "Hardware authentication challenge expired"
            )

        return pending

    @staticmethod
    def _load_public_key(value: str) -> ec.EllipticCurvePublicKey:
        try:
            der = base64.b64decode(value, validate=True)
            key = serialization.load_der_public_key(der)
        except Exception as exc:
            raise HardwareAuthError(
                "Invalid hardware public key"
            ) from exc

        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise HardwareAuthError("Hardware key is not EC")

        if not isinstance(key.curve, ec.SECP256R1):
            raise HardwareAuthError(
                "Hardware key is not P-256"
            )

        return key

    def verify_response(self, response: dict) -> dict:
        pending = self._get_pending()

        if response.get("type") != "hw_auth_response":
            raise HardwareAuthError(
                "Unexpected Stage 3 message"
            )

        if response.get("version") != PROTOCOL_VERSION:
            raise HardwareAuthError(
                "Unsupported Stage 3 version"
            )

        if response.get("algorithm") != ALGORITHM:
            raise HardwareAuthError(
                "Unsupported Stage 3 algorithm"
            )

        if response.get("session_id") != pending.session_id:
            raise HardwareAuthError(
                "Stage 3 session binding mismatch"
            )

        if response.get("challenge") != pending.challenge_b64:
            raise HardwareAuthError(
                "Stage 3 challenge mismatch"
            )

        public_b64 = response.get("hardware_public")
        signature_b64 = response.get("signature")
        attestation = response.get("attestation_chain")
        attestation_challenge = response.get(
            "attestation_challenge"
        )

        if not all(
            (
                public_b64,
                signature_b64,
                attestation,
                attestation_challenge,
            )
        ):
            raise HardwareAuthError(
                "Incomplete Stage 3 response"
            )

        if not isinstance(attestation, list) or not attestation:
            raise HardwareAuthError(
                "Missing Android attestation chain"
            )

        # ============================================================
        # CRITICAL TRUST BINDING
        # ============================================================

        if public_b64 != self._expected_hardware_public:
            self._pending = None

            raise HardwareAuthError(
                "Hardware public key does not match the registered "
                "Trusted Device hardware key"
            )

        try:
            result = verify_hardware_attestation(
                hardware_public_b64=public_b64,
                signature_b64=signature_b64,
                session_id=pending.session_id,
                challenge_b64=pending.challenge_b64,
                attestation_chain_b64=attestation,
                expected_package="com.example.lazypc",
                require_strongbox=True,
            )

            expected_attestation_challenge = (
                base64.b64decode(
                    attestation_challenge,
                    validate=True,
                )
            )

            if (
                result.info.attestation_challenge
                != expected_attestation_challenge
            ):
                raise HardwareAuthError(
                    "Attestation challenge does not match "
                    "the attested key"
                )

        except (AttestationError, ValueError) as exc:
            self._pending = None
            raise HardwareAuthError(
                str(exc)
            ) from exc

        self._pending = None

        return {
            "status": "AUTHORIZED",
            "hardware_public": public_b64,
            "attestation_challenge": attestation_challenge,
            "chain_length": result.chain_length,
            "attestation_security_level":
                result.info.attestation_security_level,
            "keymint_security_level":
                result.info.keymint_security_level,
            "verified_boot_state":
                result.info.root_of_trust.verified_boot_state,
            "device_locked":
                result.info.root_of_trust.device_locked,
            "package_names":
                result.info.package_names,
        }

    @staticmethod
    def dumps(message: dict) -> str:
        return json.dumps(
            message,
            separators=(",", ":"),
        )
