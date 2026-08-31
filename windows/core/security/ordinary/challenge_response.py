from __future__ import annotations

import argparse
import base64
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature


CHALLENGE_SIZE = 32


def create_challenge() -> bytes:
    """Create a fresh unpredictable authentication challenge."""
    return secrets.token_bytes(CHALLENGE_SIZE)


def verify_device_challenge(
    device_public_b64: str,
    challenge: bytes,
    signature_b64: str,
) -> None:
    public_der = base64.b64decode(device_public_b64)
    public_key = serialization.load_der_public_key(public_der)

    if not isinstance(public_key, ec.EllipticCurvePublicKey):
        raise RuntimeError("Device public key is not an EC key.")

    if not isinstance(public_key.curve, ec.SECP256R1):
        raise RuntimeError("Device public key is not ECDSA P-256.")

    signature = base64.b64decode(signature_b64)

    public_key.verify(
        signature,
        challenge,
        ec.ECDSA(hashes.SHA256()),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LazyPC Android challenge-response verification test."
    )
    parser.add_argument(
        "--device-public",
        required=True,
        help="Android Device public key, Base64 DER/SPKI.",
    )
    parser.add_argument(
        "--challenge",
        help="Base64 challenge. If omitted, a fresh challenge is generated.",
    )
    parser.add_argument(
        "--signature",
        help="Base64 Android ECDSA signature. Required for verification.",
    )

    args = parser.parse_args()

    if args.challenge is None:
        challenge = create_challenge()

        print("[SECURITY] Fresh challenge generated.")
        print(
            "[SECURITY] Challenge (Base64): "
            f"{base64.b64encode(challenge).decode('ascii')}"
        )
        print()
        print(
            "[SECURITY] Put this exact Base64 challenge into Android "
            "and obtain a Device signature."
        )
        return

    if args.signature is None:
        parser.error("--signature is required when --challenge is supplied.")

    challenge = base64.b64decode(args.challenge)

    if len(challenge) != CHALLENGE_SIZE:
        raise RuntimeError(
            f"Challenge must be exactly {CHALLENGE_SIZE} bytes."
        )

    try:
        verify_device_challenge(
            args.device_public,
            challenge,
            args.signature,
        )
    except InvalidSignature as error:
        raise RuntimeError(
            "Challenge signature is INVALID."
        ) from error

    print("[SECURITY] Android challenge signature: VALID")
    print("[SECURITY] ECDSA P-256 challenge-response: PASS")


if __name__ == "__main__":
    main()