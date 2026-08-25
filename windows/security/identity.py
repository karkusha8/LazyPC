from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .key_storage import ProtectedKeyStorage


@dataclass(frozen=True)
class PublicIdentity:
    device_id: str
    identity_public_key: str
    device_public_key: str
    algorithm: str = "ECDSA-P256"
    version: int = 2


class WindowsIdentity:
    """
    Owns the two persistent Windows LazyPC key pairs.

    Identity key:
        Logical identity of this Windows Agent.

    Device key:
        Independent second signing identity used later by P2P auth.
    """

    IDENTITY_NAME = "identity"
    DEVICE_NAME = "device"

    ALGORITHM = "ECDSA-P256"
    VERSION = 2

    def __init__(
        self,
        storage: ProtectedKeyStorage | None = None,
    ) -> None:
        self.storage = storage or ProtectedKeyStorage()

    def ensure_created(self) -> None:
        self._ensure_pair(self.IDENTITY_NAME)
        self._ensure_pair(self.DEVICE_NAME)

    def _ensure_pair(self, name: str) -> None:
        if self.storage.exists(name):
            return

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        private_der = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        public_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        self.storage.save_keypair(
            name=name,
            private_key_der=private_der,
            public_key_der=public_der,
            algorithm=self.ALGORITHM,
            version=self.VERSION,
        )

    def _load_private(
        self,
        name: str,
    ) -> ec.EllipticCurvePrivateKey:
        private_der, _, algorithm, version = (
            self.storage.load_keypair(name)
        )

        if algorithm != self.ALGORITHM or version != self.VERSION:
            raise RuntimeError(
                f"Unsupported LazyPC key format: "
                f"{algorithm=} {version=}"
            )

        key = serialization.load_der_private_key(
            private_der,
            password=None,
        )

        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise RuntimeError(
                "Stored private key is not an EC private key."
            )

        if not isinstance(key.curve, ec.SECP256R1):
            raise RuntimeError(
                "Stored private key is not P-256."
            )

        return key

    def _load_public_der(self, name: str) -> bytes:
        _, public_der, algorithm, version = (
            self.storage.load_keypair(name)
        )

        if algorithm != self.ALGORITHM or version != self.VERSION:
            raise RuntimeError(
                f"Unsupported LazyPC key format: "
                f"{algorithm=} {version=}"
            )

        return public_der

    def identity_public_key(self) -> bytes:
        self.ensure_created()
        return self._load_public_der(self.IDENTITY_NAME)

    def device_public_key(self) -> bytes:
        self.ensure_created()
        return self._load_public_der(self.DEVICE_NAME)

    def identity_public_key_b64(self) -> str:
        return base64.b64encode(
            self.identity_public_key()
        ).decode("ascii")

    def device_public_key_b64(self) -> str:
        return base64.b64encode(
            self.device_public_key()
        ).decode("ascii")

    def device_id(self) -> str:
        digest = hashlib.sha256(
            self.identity_public_key()
        ).digest()

        encoded = base64.urlsafe_b64encode(
            digest
        ).rstrip(b"=").decode("ascii")

        return "lazypc-" + encoded[:22]

    def public_identity(self) -> PublicIdentity:
        return PublicIdentity(
            device_id=self.device_id(),
            identity_public_key=self.identity_public_key_b64(),
            device_public_key=self.device_public_key_b64(),
        )

    def sign_identity(self, data: bytes) -> bytes:
        self.ensure_created()

        return self._load_private(
            self.IDENTITY_NAME
        ).sign(
            data,
            ec.ECDSA(hashes.SHA256()),
        )

    def sign_device(self, data: bytes) -> bytes:
        self.ensure_created()

        return self._load_private(
            self.DEVICE_NAME
        ).sign(
            data,
            ec.ECDSA(hashes.SHA256()),
        )

    def delete_all(self) -> None:
        self.storage.delete(self.IDENTITY_NAME)
        self.storage.delete(self.DEVICE_NAME)