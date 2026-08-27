from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding


ANDROID_ATTESTATION_OID = x509.ObjectIdentifier("1.3.6.1.4.1.11129.2.1.17")

# Android Key Attestation / KeyMint security levels.
SECURITY_SOFTWARE = 0
SECURITY_TEE = 1
SECURITY_STRONGBOX = 2

VERIFIED_BOOT_VERIFIED = 0
VERIFIED_BOOT_SELF_SIGNED = 1
VERIFIED_BOOT_UNVERIFIED = 2
VERIFIED_BOOT_FAILED = 3

KM_TAG_ROOT_OF_TRUST = 704
KM_TAG_ATTESTATION_APPLICATION_ID = 709

# This is the public-key hash of the Google Android Key Attestation CA1
# contained in the real chain currently returned by the test device.
# The hash is over SubjectPublicKeyInfo DER, not the certificate DER.
GOOGLE_KEY_ATTESTATION_CA1_SPKI_SHA256 = (
    "3ee44512a1af2beb39c889490c60ea3f82e43f5d5a5532f5ab9419f676cd07ec"
)


class AttestationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RootOfTrust:
    verified_boot_key: bytes
    device_locked: bool
    verified_boot_state: int
    verified_boot_hash: bytes | None


@dataclass(frozen=True)
class AttestationInfo:
    attestation_version: int
    attestation_security_level: int
    keymint_version: int
    keymint_security_level: int
    attestation_challenge: bytes
    leaf_public_key_der: bytes
    root_of_trust: RootOfTrust
    package_names: tuple[str, ...]
    signature_digests: tuple[bytes, ...]


@dataclass(frozen=True)
class VerificationResult:
    info: AttestationInfo
    chain_length: int


def _read_tlv(data: bytes, offset: int = 0):
    if offset >= len(data):
        raise AttestationError("ASN.1: unexpected end of input")

    first = data[offset]
    offset += 1

    tag_class = first & 0xC0
    constructed = bool(first & 0x20)
    low_tag = first & 0x1F

    if low_tag == 0x1F:
        tag_number = 0
        while True:
            if offset >= len(data):
                raise AttestationError("ASN.1: truncated high-tag number")
            b = data[offset]
            offset += 1
            tag_number = (tag_number << 7) | (b & 0x7F)
            if not (b & 0x80):
                break
    else:
        tag_number = low_tag

    if offset >= len(data):
        raise AttestationError("ASN.1: missing length")

    length_octet = data[offset]
    offset += 1

    if length_octet & 0x80:
        count = length_octet & 0x7F
        if count == 0:
            raise AttestationError("ASN.1: indefinite length is not supported")
        if offset + count > len(data):
            raise AttestationError("ASN.1: truncated length")
        length = int.from_bytes(data[offset:offset + count], "big")
        offset += count
    else:
        length = length_octet

    end = offset + length
    if end > len(data):
        raise AttestationError("ASN.1: value exceeds input")

    return (tag_class, constructed, tag_number), data[offset:end], end


def _children(data: bytes):
    offset = 0
    while offset < len(data):
        tag, value, offset = _read_tlv(data, offset)
        yield tag, value


def _single_tlv(data: bytes):
    tag, value, end = _read_tlv(data, 0)
    if end != len(data):
        raise AttestationError("ASN.1: trailing bytes")
    return tag, value


def _integer(value: bytes) -> int:
    if not value:
        raise AttestationError("ASN.1: empty INTEGER")
    return int.from_bytes(value, "big", signed=True)


def _unwrap_explicit(value: bytes):
    _, inner, end = _read_tlv(value, 0)
    if end != len(value):
        raise AttestationError("ASN.1: explicit value contains trailing data")
    return inner


def _parse_root_of_trust(value: bytes) -> RootOfTrust:
    # [704] EXPLICIT RootOfTrust -> SEQUENCE.
    tag, sequence_value = _single_tlv(value)
    if tag[2] != 16:
        raise AttestationError("RootOfTrust is not a SEQUENCE")

    fields = list(_children(sequence_value))
    if len(fields) < 3:
        raise AttestationError("RootOfTrust is incomplete")

    if fields[0][0][2] != 4:
        raise AttestationError("RootOfTrust.verifiedBootKey is not OCTET STRING")
    verified_boot_key = fields[0][1]

    if fields[1][0][2] != 1:
        raise AttestationError("RootOfTrust.deviceLocked is not BOOLEAN")
    device_locked = fields[1][1] != b"\x00"

    if fields[2][0][2] != 10:
        raise AttestationError("RootOfTrust.verifiedBootState is not ENUMERATED")
    verified_boot_state = _integer(fields[2][1])

    verified_boot_hash = None
    if len(fields) >= 4:
        if fields[3][0][2] != 4:
            raise AttestationError("RootOfTrust.verifiedBootHash is not OCTET STRING")
        verified_boot_hash = fields[3][1]

    return RootOfTrust(
        verified_boot_key=verified_boot_key,
        device_locked=device_locked,
        verified_boot_state=verified_boot_state,
        verified_boot_hash=verified_boot_hash,
    )


def _parse_attestation_application_id(value: bytes):
    # [709] EXPLICIT OCTET STRING. The OCTET STRING contains an ASN.1
    # AttestationApplicationId structure.
    octet_tag, body = _single_tlv(value)
    if octet_tag[2] != 4:
        raise AttestationError("AttestationApplicationId is not OCTET STRING")
    seq_tag, seq_body = _single_tlv(body)
    if seq_tag[2] != 16:
        raise AttestationError("AttestationApplicationId is not a SEQUENCE")

    fields = list(_children(seq_body))
    if len(fields) != 2:
        raise AttestationError("AttestationApplicationId has unexpected field count")

    # package_infos: SET OF SEQUENCE { package_name OCTET STRING, version INTEGER }
    package_set_tag, package_set_body = fields[0]
    if package_set_tag[2] != 17:
        raise AttestationError("AttestationApplicationId.package_infos is not SET")

    package_names: list[str] = []
    for info_tag, info_body in _children(package_set_body):
        if info_tag[2] != 16:
            raise AttestationError("Invalid AttestationPackageInfo")
        info_fields = list(_children(info_body))
        if len(info_fields) < 2 or info_fields[0][0][2] != 4:
            raise AttestationError("Invalid AttestationPackageInfo.package_name")
        package_names.append(info_fields[0][1].decode("utf-8"))

    digest_set_tag, digest_set_body = fields[1]
    if digest_set_tag[2] != 17:
        raise AttestationError("AttestationApplicationId.signature_digests is not SET")

    digests: list[bytes] = []
    for digest_tag, digest_value in _children(digest_set_body):
        if digest_tag[2] != 4:
            raise AttestationError("Invalid signature digest")
        digests.append(digest_value)

    return tuple(package_names), tuple(digests)


def _parse_key_description(extension_der: bytes, leaf: x509.Certificate) -> AttestationInfo:
    outer_tag, outer_body = _single_tlv(extension_der)
    if outer_tag[2] != 16:
        raise AttestationError("KeyDescription is not a SEQUENCE")

    fields = list(_children(outer_body))
    if len(fields) != 8:
        raise AttestationError(
            f"KeyDescription expected 8 fields, got {len(fields)}"
        )

    if fields[0][0][2] != 2:
        raise AttestationError("Invalid attestationVersion")
    attestation_version = _integer(fields[0][1])

    if fields[1][0][2] != 10:
        raise AttestationError("Invalid attestationSecurityLevel")
    attestation_security_level = _integer(fields[1][1])

    if fields[2][0][2] != 2:
        raise AttestationError("Invalid KeyMint/Keymaster version")
    keymint_version = _integer(fields[2][1])

    if fields[3][0][2] != 10:
        raise AttestationError("Invalid keyMintSecurityLevel")
    keymint_security_level = _integer(fields[3][1])

    if fields[4][0][2] != 4:
        raise AttestationError("Invalid attestationChallenge")
    attestation_challenge = fields[4][1]

    # fields[5] is uniqueId and is intentionally not used here.
    tee_tag, tee_body = fields[7]
    if tee_tag[2] != 16:
        raise AttestationError("teeEnforced is not a SEQUENCE")

    root_of_trust = None
    package_names: tuple[str, ...] = ()
    signature_digests: tuple[bytes, ...] = ()

    # RootOfTrust is expected in teeEnforced. AttestationApplicationId is
    # normally in softwareEnforced for app-generated keys, so inspect both.
    for auth_body in (fields[6][1], fields[7][1]):
        for tag, value in _children(auth_body):
            if tag[2] == KM_TAG_ROOT_OF_TRUST:
                root_of_trust = _parse_root_of_trust(value)
            elif tag[2] == KM_TAG_ATTESTATION_APPLICATION_ID:
                package_names, signature_digests = _parse_attestation_application_id(value)

    if root_of_trust is None:
        raise AttestationError("teeEnforced does not contain RootOfTrust")

    leaf_public_key_der = leaf.public_key().public_bytes(
        Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return AttestationInfo(
        attestation_version=attestation_version,
        attestation_security_level=attestation_security_level,
        keymint_version=keymint_version,
        keymint_security_level=keymint_security_level,
        attestation_challenge=attestation_challenge,
        leaf_public_key_der=leaf_public_key_der,
        root_of_trust=root_of_trust,
        package_names=package_names,
        signature_digests=signature_digests,
    )


def _verify_certificate_signature(cert: x509.Certificate, issuer: x509.Certificate) -> None:
    public_key = issuer.public_key()
    signature = cert.signature
    data = cert.tbs_certificate_bytes
    algorithm = cert.signature_hash_algorithm

    if isinstance(public_key, rsa.RSAPublicKey):
        public_key.verify(signature, data, padding.PKCS1v15(), algorithm)
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(signature, data, ec.ECDSA(algorithm))
    else:
        raise AttestationError(
            f"Unsupported attestation issuer key type: {type(public_key).__name__}"
        )


def _spki_sha256(cert: x509.Certificate) -> str:
    spki = cert.public_key().public_bytes(
        Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki).hexdigest()


def _load_chain(chain_b64: Iterable[str]) -> list[x509.Certificate]:
    certs = []
    for encoded in chain_b64:
        try:
            der = base64.b64decode(encoded, validate=True)
            certs.append(x509.load_der_x509_certificate(der))
        except Exception as exc:
            raise AttestationError("Invalid X.509 certificate in attestation chain") from exc

    if len(certs) < 2:
        raise AttestationError("Attestation chain is too short")
    return certs


def verify_hardware_session_signature(*, public_key, session_id: str, challenge_b64: str, hardware_public_b64: str, signature_b64: str) -> None:
    """Verify the exact Stage-3 transcript signed by Android."""
    if not session_id or not hardware_public_b64:
        raise AttestationError("Missing Stage-3 session binding fields")
    try:
        challenge = base64.b64decode(challenge_b64, validate=True)
        if len(challenge) != 32:
            raise ValueError("challenge must be exactly 32 bytes")
        signature = base64.b64decode(signature_b64, validate=True)
        transcript = (
            "LAZYPC_HW_AUTH_V1|SESSION|"
            f"{session_id}|{challenge_b64}|{hardware_public_b64}"
        ).encode("utf-8")
        public_key.verify(signature, transcript, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise AttestationError("WebRTC hardware signature is invalid") from exc
    except Exception as exc:
        raise AttestationError("Invalid WebRTC hardware signature material") from exc


def verify_hardware_attestation(
    *,
    hardware_public_b64: str,
    signature_b64: str,
    session_id: str,
    challenge_b64: str,
    attestation_chain_b64: Iterable[str],
    expected_package: str = "com.example.lazypc",
    expected_signature_digest: str | None = "9580090e98cf72bcad05b70caea651f7f04af76c3a481412480146fd10d62bca",
    require_strongbox: bool = True,
) -> VerificationResult:
    """Verify LazyPC Stage-3 Android Key Attestation.

    The current-session freshness comes from the ECDSA signature over the fresh
    WebRTC challenge. The attestation certificate proves that the exact public
    key used for that signature is a Google-attested StrongBox/TEE key.
    """

    certs = _load_chain(attestation_chain_b64)
    leaf = certs[0]
    root = certs[-1]

    # The chain must be ordered leaf -> issuer -> ... -> root.
    for child, issuer in zip(certs, certs[1:]):
        if child.issuer != issuer.subject:
            raise AttestationError("Attestation certificate issuer/subject mismatch")
        try:
            _verify_certificate_signature(child, issuer)
        except InvalidSignature as exc:
            raise AttestationError("Attestation certificate signature is invalid") from exc

    # Root must be self-signed and must be the Google Key Attestation CA root we trust.
    if root.subject != root.issuer:
        raise AttestationError("Attestation chain does not terminate in a self-signed root")

    try:
        _verify_certificate_signature(root, root)
    except InvalidSignature as exc:
        raise AttestationError("Attestation root self-signature is invalid") from exc

    if _spki_sha256(root) != GOOGLE_KEY_ATTESTATION_CA1_SPKI_SHA256:
        raise AttestationError("Attestation chain is not rooted in trusted Google CA1")

    # The leaf public key MUST be the key that just signed the WebRTC challenge.
    try:
        supplied_public_der = base64.b64decode(hardware_public_b64, validate=True)
        supplied_public = serialization.load_der_public_key(supplied_public_der)
    except Exception as exc:
        raise AttestationError("Invalid hardware_public key") from exc

    leaf_public_der = leaf.public_key().public_bytes(
        Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if supplied_public_der != leaf_public_der:
        raise AttestationError("hardware_public does not match attestation leaf key")

    # Session-signature verification is intentionally kept separate from
    # certificate parsing. The current Android Step-2/3 client must sign the
    # exact protocol transcript defined by the WebRTC security protocol.
    # Do not silently guess that transcript here.
    verify_hardware_session_signature(
        public_key=supplied_public,
        session_id=session_id,
        challenge_b64=challenge_b64,
        hardware_public_b64=hardware_public_b64,
        signature_b64=signature_b64,
    )

    extension = leaf.extensions.get_extension_for_oid(ANDROID_ATTESTATION_OID)
    info = _parse_key_description(extension.value.value, leaf)

    if info.attestation_security_level != (
        SECURITY_STRONGBOX if require_strongbox else SECURITY_TEE
    ):
        expected = "STRONGBOX" if require_strongbox else "TEE/STRONGBOX"
        raise AttestationError(
            f"Attestation security level is not {expected}: "
            f"{info.attestation_security_level}"
        )

    if require_strongbox and info.keymint_security_level != SECURITY_STRONGBOX:
        raise AttestationError("KeyMint security level is not StrongBox")

    if info.root_of_trust.device_locked is not True:
        raise AttestationError("Android bootloader/device is not locked")

    if info.root_of_trust.verified_boot_state != VERIFIED_BOOT_VERIFIED:
        raise AttestationError(
            "Android Verified Boot state is not VERIFIED: "
            f"{info.root_of_trust.verified_boot_state}"
        )

    if expected_package not in info.package_names:
        raise AttestationError(
            f"AttestationApplicationId does not contain {expected_package!r}"
        )

    if expected_signature_digest is not None:
        normalized = expected_signature_digest.lower()
        if normalized not in {digest.hex().lower() for digest in info.signature_digests}:
            raise AttestationError(
                "Android application signing certificate digest is not trusted"
            )

    return VerificationResult(
        info=info,
        chain_length=len(certs),
    )