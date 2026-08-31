from __future__ import annotations

import base64
import secrets
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .attestation_verifier import AttestationError, verify_hardware_attestation
from security.common.identity import WindowsIdentity
from .pairing import TrustedDeviceStore


PAIRING_VERSION = 3
PAIRING_ALGORITHM = "ECDSA-P256-HW-ATTESTATION-V3"
PAIRING_TTL_SECONDS = 120.0
PAIRING_NONCE_SIZE = 32


class TrustedPairingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PairingInvitation:
    pairing_id: str
    token: str
    nonce_b64: str
    pc_identity_public: str
    expires_at: float

    def qr_payload(self) -> str:
        return (
            "LAZYPC_PAIR_V2|"
            f"{self.pairing_id}|"
            f"{self.token}|"
            f"{self.nonce_b64}|"
            f"{self.pc_identity_public}"
        )


class TrustedPairingManager:
    def __init__(self) -> None:
        self.identity = WindowsIdentity()
        self.identity.ensure_created()
        self.store = TrustedDeviceStore()
        self._pending: PairingInvitation | None = None

    def begin(self) -> PairingInvitation:
        invitation = PairingInvitation(
            pairing_id=secrets.token_hex(16),
            token=secrets.token_urlsafe(24),
            nonce_b64=base64.b64encode(
                secrets.token_bytes(PAIRING_NONCE_SIZE)
            ).decode("ascii"),
            pc_identity_public=self.identity.identity_public_key_b64(),
            expires_at=time.monotonic() + PAIRING_TTL_SECONDS,
        )
        self._pending = invitation
        return invitation

    def _get_pending(self) -> PairingInvitation:
        if self._pending is None:
            raise TrustedPairingError("No Trusted Device pairing is active.")
        if time.monotonic() > self._pending.expires_at:
            self._pending = None
            raise TrustedPairingError("Trusted Device pairing expired.")
        return self._pending

    def accept_signaling_token(self, token: str) -> PairingInvitation:
        pending = self._get_pending()
        if not secrets.compare_digest(token, pending.token):
            raise TrustedPairingError("Invalid pairing token.")
        return pending

    @staticmethod
    def _load_public_key(value: str) -> ec.EllipticCurvePublicKey:
        try:
            key = serialization.load_der_public_key(
                base64.b64decode(value, validate=True)
            )
        except Exception as exc:
            raise TrustedPairingError("Invalid Android public key.") from exc

        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise TrustedPairingError("Android key is not EC.")
        if not isinstance(key.curve, ec.SECP256R1):
            raise TrustedPairingError("Android key is not P-256.")
        return key

    @staticmethod
    def _verify(public_key_b64: str, message: bytes, signature_b64: str) -> None:
        key = TrustedPairingManager._load_public_key(public_key_b64)
        try:
            signature = base64.b64decode(signature_b64, validate=True)
            key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        except Exception as exc:
            raise TrustedPairingError("Pairing signature is invalid.") from exc

    def challenge(self, token: str) -> dict:
        pending = self.accept_signaling_token(token)
        return {
            "type": "pair_challenge",
            "version": PAIRING_VERSION,
            "algorithm": PAIRING_ALGORITHM,
            "pairing_id": pending.pairing_id,
            "nonce": pending.nonce_b64,
            "pc_identity_public": pending.pc_identity_public,
        }

    def verify_and_register(self, response: dict) -> dict:
        pending = self._get_pending()

        if response.get("type") != "pair_response":
            raise TrustedPairingError("Unexpected pairing response.")
        if response.get("version") != PAIRING_VERSION:
            raise TrustedPairingError("Unsupported pairing version.")
        if response.get("algorithm") != PAIRING_ALGORITHM:
            raise TrustedPairingError("Unsupported pairing algorithm.")
        if response.get("pairing_id") != pending.pairing_id:
            raise TrustedPairingError("Pairing session mismatch.")
        if response.get("nonce") != pending.nonce_b64:
            raise TrustedPairingError("Pairing nonce mismatch.")
        if response.get("pc_identity_public") != pending.pc_identity_public:
            raise TrustedPairingError("PC identity mismatch.")

        identity_public = response.get("identity_public")
        device_public = response.get("device_public")
        hardware_public = response.get("hardware_public")
        identity_binding_signature = response.get("identity_binding_signature")
        device_enrollment_signature = response.get("device_enrollment_signature")
        hardware_signature = response.get("hardware_signature")
        attestation_chain = response.get("attestation_chain")
        attestation_challenge = response.get("attestation_challenge")

        platform = response.get("platform")
        manufacturer = response.get("manufacturer")
        model = response.get("model")
        android_version = response.get("android_version")

        if not all((
            identity_public,
            device_public,
            hardware_public,
            identity_binding_signature,
            device_enrollment_signature,
            hardware_signature,
            attestation_chain,
            attestation_challenge,
        )):
            raise TrustedPairingError("Incomplete pairing response.")

        if not isinstance(attestation_chain, list) or not attestation_chain:
            raise TrustedPairingError("Missing Android attestation chain.")

        identity_binding_transcript = (
            "LAZYPC_IDENTITY_BIND_V2|"
            f"{pending.pairing_id}|"
            f"{pending.nonce_b64}|"
            f"{pending.pc_identity_public}|"
            f"{identity_public}|"
            f"{device_public}"
        ).encode("utf-8")

        device_enrollment_transcript = (
            "LAZYPC_DEVICE_ENROLL_V2|"
            f"{pending.pairing_id}|"
            f"{pending.nonce_b64}|"
            f"{pending.pc_identity_public}|"
            f"{identity_public}|"
            f"{device_public}"
        ).encode("utf-8")

        self._verify(
            identity_public,
            identity_binding_transcript,
            identity_binding_signature,
        )
        self._verify(
            device_public,
            device_enrollment_transcript,
            device_enrollment_signature,
        )

        try:
            result = verify_hardware_attestation(
                hardware_public_b64=hardware_public,
                signature_b64=hardware_signature,
                session_id=pending.pairing_id,
                challenge_b64=pending.nonce_b64,
                attestation_chain_b64=attestation_chain,
                expected_package="com.example.lazypc",
                require_strongbox=True,
            )
        except (AttestationError, ValueError) as exc:
            self._pending = None
            raise TrustedPairingError(str(exc)) from exc

        # IMPORTANT:
        # The StrongBox key may pre-exist this PC pairing. Therefore its
        # attestation challenge is NOT required to equal this PC's nonce.
        # We only require the reported challenge to equal the challenge
        # actually embedded in the attestation certificate.
        expected_attestation_challenge = base64.b64decode(
            attestation_challenge,
            validate=True,
        )
        if result.info.attestation_challenge != expected_attestation_challenge:
            self._pending = None
            raise TrustedPairingError(
                "Attestation challenge does not match the attested key."
            )

        device_id = self.store.register_device(
            pc_identity_public=pending.pc_identity_public,
            identity_public=identity_public,
            device_public=device_public,
            hardware_public=hardware_public,
            identity_binding_signature=identity_binding_signature,
            pairing_id=pending.pairing_id,
            pairing_nonce=pending.nonce_b64,
            hardware_algorithm="ECDSA-P256",
            hardware_security="StrongBox",
            attestation_challenge=attestation_challenge,
            platform=platform,
            manufacturer=manufacturer,
            model=model,
            android_version=android_version,
        )

        self._pending = None

        return {
            "status": "PAIRED",
            "device_id": device_id,
            "pc_identity_public": pending.pc_identity_public,
            "identity_public": identity_public,
            "device_public": device_public,
            "hardware_public": hardware_public,
            "attestation_security_level": result.info.attestation_security_level,
            "keymint_security_level": result.info.keymint_security_level,
            "verified_boot_state": result.info.root_of_trust.verified_boot_state,
            "device_locked": result.info.root_of_trust.device_locked,
        }
