from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding

"""Android Key Attestation verification (v4).

Runs ONCE, at pairing. After that the PC trusts only the pinned StrongBox
public key and checks signatures against it; the certificate chain is not
re-verified per session (it adds nothing once the key is pinned, and a Google
root rotation could otherwise lock every paired phone out).

The ASN.1 parsing helpers are unchanged from the previous version.
"""

ANDROID_ATTESTATION_OID = x509.ObjectIdentifier("1.3.6.1.4.1.11129.2.1.17")

# Android Key Attestation / KeyMint security levels.
SECURITY_SOFTWARE = 0
SECURITY_TEE = 1
SECURITY_STRONGBOX = 2

VERIFIED_BOOT_VERIFIED = 0
VERIFIED_BOOT_SELF_SIGNED = 1
VERIFIED_BOOT_UNVERIFIED = 2
VERIFIED_BOOT_FAILED = 3

# KeyMint authorization tags (tag number inside the context-specific class).
KM_TAG_PURPOSE = 1
KM_TAG_NO_AUTH_REQUIRED = 503
KM_TAG_USER_AUTH_TYPE = 504
KM_TAG_AUTH_TIMEOUT = 505
KM_TAG_ORIGIN = 702
KM_TAG_ROOT_OF_TRUST = 704
KM_TAG_ATTESTATION_APPLICATION_ID = 709

KM_ORIGIN_GENERATED = 0
KM_PURPOSE_SIGN = 2
KM_PURPOSE_VERIFY = 3
HW_AUTH_BIOMETRIC = 2          # HardwareAuthenticatorType.FINGERPRINT bit

_CONTEXT_CLASS = 0x80

# SPKI SHA-256 of trusted attestation roots. The hash is over
# SubjectPublicKeyInfo DER, not the certificate DER. Add Google's other
# published roots here: they rotate, and a single pin will eventually lock
# out some devices.
GOOGLE_KEY_ATTESTATION_CA1_SPKI_SHA256 = (
    "3ee44512a1af2beb39c889490c60ea3f82e43f5d5a5532f5ab9419f676cd07ec"
)
TRUSTED_ROOT_SPKI_SHA256 = frozenset({GOOGLE_KEY_ATTESTATION_CA1_SPKI_SHA256})


class AttestationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AttestationPolicy:
    expected_package: str = "com.example.lazypc"
    # Hex SHA-256 digests of the app signing certificate. Empty tuple = skip.
    expected_signature_digests: tuple[str, ...] = (
        "9580090e98cf72bcad05b70caea651f7f04af76c3a481412480146fd10d62bca",
    )
    trusted_root_spki_sha256: frozenset = TRUSTED_ROOT_SPKI_SHA256
    require_strongbox: bool = True
    # Key must have been generated inside the secure hardware, not imported.
    require_generated_key: bool = True
    # Require per-use user authentication (biometric). Off by default so an
    # existing key without it is not locked out; turn it on once the Android
    # side generates the key with setUserAuthenticationRequired(true).
    require_user_auth: bool = False


@dataclass(frozen=True)
class RootOfTrust:
    verified_boot_key: bytes
    device_locked: bool
    verified_boot_state: int
    verified_boot_hash: "bytes | None"


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
    purposes: tuple[int, ...] = ()
    origin: "int | None" = None
    no_auth_required: bool = False
    user_auth_type: "int | None" = None
    auth_timeout: "int | None" = None


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
    if fields[6][0][2] != 16:
        raise AttestationError("softwareEnforced is not a SEQUENCE")
    if fields[7][0][2] != 16:
        raise AttestationError("teeEnforced is not a SEQUENCE")

    root_of_trust = None
    package_names: tuple[str, ...] = ()
    signature_digests: tuple[bytes, ...] = ()
    purposes: tuple[int, ...] = ()
    origin = None
    no_auth_required = False
    user_auth_type = None
    auth_timeout = None

    # AttestationApplicationId normally sits in softwareEnforced (filled in by
    # the Android framework), so look in both lists for it.
    for auth_body in (fields[6][1], fields[7][1]):
        for tag, value in _children(auth_body):
            if tag[0] == _CONTEXT_CLASS and tag[2] == KM_TAG_ATTESTATION_APPLICATION_ID:
                package_names, signature_digests = _parse_attestation_application_id(value)

    # Everything security-relevant is taken ONLY from teeEnforced: the
    # hardware vouches for it, the OS-side list is not trusted for it.
    for tag, value in _children(fields[7][1]):
        if tag[0] != _CONTEXT_CLASS:
            continue
        number = tag[2]
        if number == KM_TAG_ROOT_OF_TRUST:
            root_of_trust = _parse_root_of_trust(value)
        elif number == KM_TAG_PURPOSE:
            purposes = tuple(
                _integer(v) for _, v in _children(_unwrap_explicit(value))
            )
        elif number == KM_TAG_ORIGIN:
            origin = _integer(_unwrap_explicit(value))
        elif number == KM_TAG_NO_AUTH_REQUIRED:
            no_auth_required = True
        elif number == KM_TAG_USER_AUTH_TYPE:
            user_auth_type = _integer(_unwrap_explicit(value))
        elif number == KM_TAG_AUTH_TIMEOUT:
            auth_timeout = _integer(_unwrap_explicit(value))

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
        purposes=purposes,
        origin=origin,
        no_auth_required=no_auth_required,
        user_auth_type=user_auth_type,
        auth_timeout=auth_timeout,
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
    if len(certs) > 8:
        raise AttestationError("Attestation chain is too long")
    return certs


def _validity(cert: x509.Certificate) -> tuple[datetime, datetime]:
    before = getattr(cert, "not_valid_before_utc", None)
    after = getattr(cert, "not_valid_after_utc", None)
    if before is None or after is None:          # older cryptography
        before = cert.not_valid_before.replace(tzinfo=timezone.utc)
        after = cert.not_valid_after.replace(tzinfo=timezone.utc)
    return before, after


def verify_attestation_chain(
    *,
    hardware_public_der: bytes,
    attestation_chain_b64: Iterable[str],
    policy: AttestationPolicy = AttestationPolicy(),
    now: "datetime | None" = None,
    is_revoked: "Callable[[str], bool] | None" = None,
) -> VerificationResult:
    """Verify that `hardware_public_der` is an attested, non-exportable key in
    the secure hardware of a locked, verified-boot device running our app.

    It does NOT check freshness: the caller must compare
    result.info.attestation_challenge with the pairing nonce.

    is_revoked(serial_hex) -> bool is a hook for Google's attestation status
    list (certificate serials as lowercase hex without leading zeros).
    """
    now = now or datetime.now(timezone.utc)
    certs = _load_chain(attestation_chain_b64)
    leaf = certs[0]
    root = certs[-1]

    for cert in certs:
        before, after = _validity(cert)
        if not (before <= now <= after):
            raise AttestationError("Attestation certificate is outside its validity period")
        if is_revoked is not None and is_revoked(format(cert.serial_number, "x")):
            raise AttestationError("Attestation certificate has been revoked")

    # The chain must be ordered leaf -> issuer -> ... -> root.
    for child, issuer in zip(certs, certs[1:]):
        if child.issuer != issuer.subject:
            raise AttestationError("Attestation certificate issuer/subject mismatch")
        try:
            _verify_certificate_signature(child, issuer)
        except InvalidSignature as exc:
            raise AttestationError("Attestation certificate signature is invalid") from exc

    for issuer in certs[1:]:
        try:
            constraints = issuer.extensions.get_extension_for_class(
                x509.BasicConstraints).value
        except x509.ExtensionNotFound as exc:
            raise AttestationError("Issuer certificate has no BasicConstraints") from exc
        if not constraints.ca:
            raise AttestationError("Issuer certificate is not a CA")

    if root.subject != root.issuer:
        raise AttestationError("Attestation chain does not terminate in a self-signed root")
    try:
        _verify_certificate_signature(root, root)
    except InvalidSignature as exc:
        raise AttestationError("Attestation root self-signature is invalid") from exc

    if _spki_sha256(root) not in policy.trusted_root_spki_sha256:
        raise AttestationError("Attestation chain is not rooted in a trusted Google CA")

    leaf_public_der = leaf.public_key().public_bytes(
        Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if hardware_public_der != leaf_public_der:
        raise AttestationError("hardware_public does not match attestation leaf key")

    try:
        extension = leaf.extensions.get_extension_for_oid(ANDROID_ATTESTATION_OID)
    except x509.ExtensionNotFound as exc:
        raise AttestationError("Leaf certificate has no Android attestation extension") from exc
    info = _parse_key_description(extension.value.value, leaf)

    allowed_levels = (
        {SECURITY_STRONGBOX} if policy.require_strongbox
        else {SECURITY_TEE, SECURITY_STRONGBOX}
    )
    if info.attestation_security_level not in allowed_levels:
        expected = "STRONGBOX" if policy.require_strongbox else "TEE/STRONGBOX"
        raise AttestationError(
            f"Attestation security level is not {expected}: "
            f"{info.attestation_security_level}"
        )

    if policy.require_strongbox and info.keymint_security_level != SECURITY_STRONGBOX:
        raise AttestationError("KeyMint security level is not StrongBox")

    if info.root_of_trust.device_locked is not True:
        raise AttestationError("Android bootloader/device is not locked")

    if info.root_of_trust.verified_boot_state != VERIFIED_BOOT_VERIFIED:
        raise AttestationError(
            "Android Verified Boot state is not VERIFIED: "
            f"{info.root_of_trust.verified_boot_state}"
        )

    if policy.expected_package not in info.package_names:
        raise AttestationError(
            f"AttestationApplicationId does not contain {policy.expected_package!r}"
        )

    if policy.expected_signature_digests:
        trusted = {d.lower() for d in policy.expected_signature_digests}
        if not trusted & {digest.hex().lower() for digest in info.signature_digests}:
            raise AttestationError(
                "Android application signing certificate digest is not trusted"
            )

    if policy.require_generated_key and info.origin != KM_ORIGIN_GENERATED:
        raise AttestationError(
            f"Key was not generated in secure hardware (origin={info.origin})"
        )

    if KM_PURPOSE_SIGN not in info.purposes or not set(info.purposes) <= {
            KM_PURPOSE_SIGN, KM_PURPOSE_VERIFY}:
        raise AttestationError(f"Key purposes are not sign-only: {info.purposes}")

    if policy.require_user_auth:
        if info.no_auth_required or not info.user_auth_type or not (
                info.user_auth_type & HW_AUTH_BIOMETRIC):
            raise AttestationError(
                "Key does not require biometric user authentication "
                f"(noAuthRequired={info.no_auth_required}, "
                f"userAuthType={info.user_auth_type})"
            )

    return VerificationResult(info=info, chain_length=len(certs))
