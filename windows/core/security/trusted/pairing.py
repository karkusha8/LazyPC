

import base64

from .database import LazyPCDatabase


class TrustedDeviceStore:
    """
    Persistent registry of explicitly paired Trusted Devices.

    Storage is SQLite via LazyPCDatabase.

    IMPORTANT:
    - Normal/ordinary authentication never creates entries here.
    - register_device() is used only by the explicit Trusted pairing flow.
    - Private keys are never stored here.
    """

    def __init__(self) -> None:
        self.database = LazyPCDatabase()

    @staticmethod
    def device_id(device_public: str) -> str:
        return LazyPCDatabase.device_id(device_public)

    def get_device(
        self,
        identity_public: str,
        device_public: str,
    ) -> dict | None:
        return self.database.get_trusted_device(
            identity_public,
            device_public,
        )

    def is_paired(
        self,
        identity_public: str,
        device_public: str,
    ) -> bool:
        return (
            self.get_device(
                identity_public,
                device_public,
            )
            is not None
        )

    def hardware_public_for(
        self,
        identity_public: str,
        device_public: str,
    ) -> str | None:
        entry = self.get_device(
            identity_public,
            device_public,
        )

        if entry is None:
            return None

        value = entry.get("hardware_public")

        return value if isinstance(value, str) and value else None

    def has_hardware_binding(
        self,
        identity_public: str,
        device_public: str,
    ) -> bool:
        return (
            self.hardware_public_for(
                identity_public,
                device_public,
            )
            is not None
        )

    def register_device(
        self,
        identity_public: str,
        device_public: str,
        hardware_public: str,
        *,
        pc_identity_public: str,
        identity_binding_signature: str,
        pairing_id: str,
        pairing_nonce: str,
        hardware_algorithm: str = "ECDSA-P256",
        hardware_security: str = "StrongBox",
        attestation_challenge: str | None = None,
        platform: str | None = None,
        manufacturer: str | None = None,
        model: str | None = None,
        android_version: str | None = None,
    ) -> str:
        required = (
            identity_public,
            device_public,
            hardware_public,
            pc_identity_public,
            identity_binding_signature,
            pairing_id,
            pairing_nonce,
        )

        if not all(required):
            raise ValueError(
                "Incomplete Trusted Device enrollment data."
            )

        # Keep the same validation behavior as the existing store.
        try:
            for value in (
                identity_public,
                device_public,
                hardware_public,
                pc_identity_public,
                identity_binding_signature,
                pairing_nonce,
            ):
                base64.b64decode(
                    value,
                    validate=True,
                )
        except Exception as exc:
            raise ValueError(
                "Invalid base64 security data."
            ) from exc

        # A pairing belongs to the PC Identity + Android Identity pair.
        # A new QR pairing rotates only the Device Key, so remove the
        # previous registration for that same pair before inserting the
        # new Device Key.
        existing_devices = self.database.list_trusted_devices()

        for existing in existing_devices:
            if (
                existing.get("pc_identity_public")
                == pc_identity_public
                and existing.get("identity_public")
                == identity_public
                and existing.get("device_id")
                != self.device_id(device_public)
            ):
                old_device_public = existing.get("device_public")

                if isinstance(old_device_public, str):
                    self.database.remove_trusted_device(
                        old_device_public
                    )

        device_id = self.device_id(device_public)

        self.database.upsert_trusted_device(
            {
                "device_id": device_id,
                "pc_identity_public": pc_identity_public,
                "identity_public": identity_public,
                "device_public": device_public,
                "hardware_public": hardware_public,
                "identity_binding_signature":
                    identity_binding_signature,
                "pairing_id": pairing_id,
                "pairing_nonce": pairing_nonce,
                "hardware_algorithm": hardware_algorithm,
                "hardware_security": hardware_security,
                "attestation_challenge":
                    attestation_challenge,
                "algorithm":
                    "ECDSA-P256-TRUSTED-V3",
                "version": 4,

                # Device presentation metadata is intentionally nullable.
                # We can populate these fields later when the Android
                # identity/device metadata is passed through the pairing
                # protocol.
                "platform": platform,
                "manufacturer": manufacturer,
                "model": model,
                "android_version": android_version,
                "display_name": None,
                "enabled": 1,
                "created_at": None,
                "last_seen_at": None,
            }
        )

        return device_id

    def remove(self, device_public: str) -> bool:
        return self.database.remove_trusted_device(
            device_public
        )

    def list_devices(self) -> list[dict]:
        return self.database.list_trusted_devices()

    def mark_seen(self, device_id: str) -> None:
        self.database.mark_trusted_device_seen(device_id)
