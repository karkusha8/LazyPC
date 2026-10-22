from __future__ import annotations

from .database import LazyPCDatabase
from .secure_link import TrustedPhone


class TrustedDeviceStore:
    """Registry of explicitly paired phones (implements secure_link.PhoneStore).

    Entries are created only by the explicit pairing flow, after the person at
    the PC pressed Allow. Only public keys are stored.
    """

    def __init__(self, database: "LazyPCDatabase | None" = None,
                 pc_static_pub: "bytes | None" = None) -> None:
        self.database = database or LazyPCDatabase()
        self._pc_static_pub = pc_static_pub

    def find(self, phone_static: bytes) -> "TrustedPhone | None":
        row = self.database.find_by_static(phone_static)
        if row is None:
            return None
        if self._pc_static_pub is not None and row["pc_static"] != self._pc_static_pub:
            return None                      # paired with a previous PC key
        return TrustedPhone(
            device_id=row["device_id"],
            phone_static=bytes(row["phone_static"]),
            hw_public_der=bytes(row["hw_public"]),
            enabled=bool(row["enabled"]),
        )

    def add(self, phone: TrustedPhone, meta: dict) -> None:
        if self._pc_static_pub is None:
            raise RuntimeError("Store needs the PC static public key to add devices.")
        self.database.add_phone({
            "device_id": phone.device_id,
            "phone_static": phone.phone_static,
            "hw_public": phone.hw_public_der,
            "pc_static": self._pc_static_pub,
            "platform": meta.get("platform"),
            "manufacturer": meta.get("manufacturer"),
            "model": meta.get("model"),
            "android_version": meta.get("android_version"),
        })

    def list_devices(self) -> list[dict]:
        return self.database.list_phones()

    def rename(self, device_id: str, display_name: str) -> bool:
        return self.database.rename(device_id, display_name)

    def remove(self, device_id: str) -> bool:
        return self.database.remove(device_id)

    def set_enabled(self, device_id: str, enabled: bool) -> bool:
        return self.database.set_enabled(device_id, enabled)

    def mark_seen(self, device_id: str) -> None:
        self.database.mark_seen(device_id)
