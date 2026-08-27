import base64
import hashlib
import json
import os
from pathlib import Path


class TrustedDeviceStore:
    FILE_NAME = "trusted_devices.json"
    VERSION = 4

    def __init__(self) -> None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is unavailable.")

        self.root = Path(local_app_data) / "LazyPC" / "security"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / self.FILE_NAME

    def _load(self) -> dict:
        default = {"version": self.VERSION, "devices": {}}

        if not self.path.exists():
            return default

        try:
            raw = self.path.read_text(encoding="utf-8").strip()
            if not raw:
                return default
            data = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return default

        if not isinstance(data, dict):
            return default

        version = data.get("version")
        if version not in (3, self.VERSION):
            raise RuntimeError("Unsupported trusted device store version.")

        if not isinstance(data.get("devices"), dict):
            return default

        return data

    def _save(self, data: dict) -> None:
        data["version"] = self.VERSION
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    @staticmethod
    def device_id(device_public: str) -> str:
        digest = hashlib.sha256(device_public.encode("ascii")).hexdigest()
        return "android-" + digest[:24]

    def get_device(self, identity_public: str, device_public: str) -> dict | None:
        data = self._load()
        entry = data["devices"].get(self.device_id(device_public))
        if entry is None:
            return None

        if (
            entry.get("identity_public") != identity_public
            or entry.get("device_public") != device_public
            or not entry.get("pc_identity_public")
        ):
            return None

        return dict(entry)

    def hardware_public_for(self, identity_public: str, device_public: str) -> str | None:
        entry = self.get_device(identity_public, device_public)
        if entry is None:
            return None
        value = entry.get("hardware_public")
        return value if isinstance(value, str) and value else None

    def has_hardware_binding(self, identity_public: str, device_public: str) -> bool:
        return self.hardware_public_for(identity_public, device_public) is not None

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
            raise ValueError("Incomplete Trusted Device enrollment data.")

        try:
            for value in (
                identity_public,
                device_public,
                hardware_public,
                pc_identity_public,
                identity_binding_signature,
                pairing_nonce,
            ):
                base64.b64decode(value, validate=True)
        except Exception as exc:
            raise ValueError("Invalid base64 security data.") from exc

        data = self._load()

        # A pairing belongs to the PC Identity + Android Identity pair.
        # A new QR pairing rotates only the Device Key, so replace any
        # previous registration for the same PC/Android pair.
        stale_ids = [
            existing_id
            for existing_id, existing in data["devices"].items()
            if (
                existing.get("pc_identity_public") == pc_identity_public
                and existing.get("identity_public") == identity_public
            )
        ]

        for existing_id in stale_ids:
            del data["devices"][existing_id]

        device_id = self.device_id(device_public)

        data["devices"][device_id] = {
            "pc_identity_public": pc_identity_public,
            "identity_public": identity_public,
            "device_public": device_public,
            "identity_binding_signature": identity_binding_signature,
            "pairing_id": pairing_id,
            "pairing_nonce": pairing_nonce,
            "hardware_public": hardware_public,
            "hardware_algorithm": hardware_algorithm,
            "hardware_security": hardware_security,
            "attestation_challenge": attestation_challenge,
            "algorithm": "ECDSA-P256-TRUSTED-V3",
            "version": 4,
        }

        self._save(data)
        return device_id

    def remove(self, device_public: str) -> bool:
        data = self._load()
        device_id = self.device_id(device_public)
        if device_id not in data["devices"]:
            return False
        del data["devices"][device_id]
        self._save(data)
        return True

    def list_devices(self) -> list[dict]:
        return list(self._load()["devices"].values())
