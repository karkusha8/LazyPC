from __future__ import annotations

import base64
import secrets
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from core.security.pairing import TrustedDeviceStore
from core.security.identity import WindowsIdentity


AUTH_VERSION = 3
AUTH_ALGORITHM = "ECDSA-P256-TRUSTED-V3"
CHALLENGE_SIZE = 32
CHALLENGE_TTL_SECONDS = 15.0


class AndroidAuthenticator:
    def __init__(self) -> None:
        self._challenge: bytes | None = None
        self._created_at: float | None = None
        self.trusted_devices = TrustedDeviceStore()
        self.identity = WindowsIdentity()
        self.identity.ensure_created()

    def create_challenge(self) -> str:
        challenge = secrets.token_bytes(CHALLENGE_SIZE)
        self._challenge = challenge
        self._created_at = time.monotonic()
        return base64.b64encode(challenge).decode("ascii")

    def challenge_payload(self) -> dict:
        return {
            "type": "auth_challenge",
            "version": AUTH_VERSION,
            "algorithm": AUTH_ALGORITHM,
            "challenge": self.create_challenge(),
            "pc_identity_public": self.identity.identity_public_key_b64(),
        }

    def _get_challenge(self) -> bytes:
        if self._challenge is None:
            raise RuntimeError("No authentication challenge is pending.")
        if self._created_at is None:
            raise RuntimeError("Authentication challenge timestamp is missing.")
        if time.monotonic() - self._created_at > CHALLENGE_TTL_SECONDS:
            self._challenge = None
            self._created_at = None
            raise RuntimeError("Authentication challenge expired.")
        return self._challenge

    @staticmethod
    def _load_public_key(value: str) -> ec.EllipticCurvePublicKey:
        try:
            key = serialization.load_der_public_key(
                base64.b64decode(value, validate=True)
            )
        except Exception as exc:
            raise RuntimeError("Invalid Android public key.") from exc

        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise RuntimeError("Android public key is not EC.")
        if not isinstance(key.curve, ec.SECP256R1):
            raise RuntimeError("Android public key is not P-256.")
        return key

    @staticmethod
    def _verify(public_key_b64: str, message: bytes, signature_b64: str) -> None:
        key = AndroidAuthenticator._load_public_key(public_key_b64)
        try:
            signature = base64.b64decode(signature_b64, validate=True)
            key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except Exception as exc:
            raise RuntimeError("Authentication signature is invalid.") from exc

    def verify_response(self, response: dict) -> dict:
        challenge = self._get_challenge()

        if response.get("type") != "auth_response":
            raise RuntimeError("Unexpected authentication message.")
        if response.get("version") != AUTH_VERSION:
            raise RuntimeError("Unsupported authentication version.")
        if response.get("algorithm") != AUTH_ALGORITHM:
            raise RuntimeError("Unsupported authentication algorithm.")

        pc_identity_public = response.get("pc_identity_public")
        identity_public = response.get("identity_public")
        device_public = response.get("device_public")
        identity_binding_signature = response.get("identity_binding_signature")
        device_signature = response.get("device_signature")

        if not all((
            pc_identity_public,
            identity_public,
            device_public,
            identity_binding_signature,
            device_signature,
        )):
            raise RuntimeError("Incomplete authentication response.")

        expected_pc = self.identity.identity_public_key_b64()
        if pc_identity_public != expected_pc:
            self._challenge = None
            self._created_at = None
            raise RuntimeError("PC identity binding mismatch.")

        trusted_entry = self.trusted_devices.get_device(
            identity_public,
            device_public,
        )

        if trusted_entry is None:
            self._challenge = None
            self._created_at = None
            raise RuntimeError("Android device is not a registered Trusted Device.")

        if trusted_entry.get("pc_identity_public") != expected_pc:
            self._challenge = None
            self._created_at = None
            raise RuntimeError("Trusted Device is registered for another PC.")

        stored_binding_signature = trusted_entry.get("identity_binding_signature")
        pairing_id = trusted_entry.get("pairing_id")
        pairing_nonce = trusted_entry.get("pairing_nonce")

        if not all((stored_binding_signature, pairing_id, pairing_nonce)):
            self._challenge = None
            self._created_at = None
            raise RuntimeError("Trusted Device requires re-enrollment.")

        identity_binding_transcript = (
            "LAZYPC_IDENTITY_BIND_V2|"
            f"{pairing_id}|"
            f"{pairing_nonce}|"
            f"{expected_pc}|"
            f"{identity_public}|"
            f"{device_public}"
        ).encode("utf-8")

        self._verify(
            identity_public,
            identity_binding_transcript,
            stored_binding_signature,
        )

        challenge_b64 = base64.b64encode(challenge).decode("ascii")

        device_transcript = (
            "LAZYPC_AUTH_V2|DEVICE|"
            f"{expected_pc}|{challenge_b64}"
        ).encode("utf-8")

        self._verify(device_public, device_transcript, device_signature)

        self._challenge = None
        self._created_at = None

        return {
            "identity_public": identity_public,
            "device_public": device_public,
            "hardware_public": trusted_entry.get("hardware_public"),
            "device_id": self.trusted_devices.device_id(device_public),
        }
