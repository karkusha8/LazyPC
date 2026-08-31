from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


class LazyPCDatabase:
    """Small synchronous SQLite database used for persistent LazyPC state."""

    DB_NAME = "lazypc.db"

    def __init__(self) -> None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is unavailable.")

        self.root = Path(local_app_data) / "LazyPC"
        self.root.mkdir(parents=True, exist_ok=True)

        self.path = self.root / self.DB_NAME
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trusted_devices (
                    device_id TEXT PRIMARY KEY,

                    pc_identity_public TEXT NOT NULL,
                    identity_public TEXT NOT NULL,
                    device_public TEXT NOT NULL,
                    hardware_public TEXT NOT NULL,

                    identity_binding_signature TEXT NOT NULL,
                    pairing_id TEXT NOT NULL,
                    pairing_nonce TEXT NOT NULL,

                    hardware_algorithm TEXT NOT NULL DEFAULT 'ECDSA-P256',
                    hardware_security TEXT NOT NULL DEFAULT 'StrongBox',
                    attestation_challenge TEXT,

                    algorithm TEXT NOT NULL DEFAULT 'ECDSA-P256-TRUSTED-V3',
                    version INTEGER NOT NULL DEFAULT 4,

                    platform TEXT,
                    manufacturer TEXT,
                    model TEXT,
                    android_version TEXT,

                    display_name TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,

                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT
                )
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trusted_devices_identity
                ON trusted_devices(identity_public)
                """
            )

            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trusted_devices_device_public
                ON trusted_devices(device_public)
                """
            )

    def upsert_trusted_device(self, device: dict[str, Any]) -> None:
        print("[DB] upsert_trusted_device received:")
        for key, value in device.items():
            print(f"[DB]   {key} = {value!r}")
        required = (
            "device_id",
            "pc_identity_public",
            "identity_public",
            "device_public",
            "hardware_public",
            "identity_binding_signature",
            "pairing_id",
            "pairing_nonce",
        )

        if not all(device.get(key) for key in required):
            raise ValueError("Incomplete Trusted Device database record.")

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trusted_devices (
                    device_id,
                    pc_identity_public,
                    identity_public,
                    device_public,
                    hardware_public,
                    identity_binding_signature,
                    pairing_id,
                    pairing_nonce,
                    hardware_algorithm,
                    hardware_security,
                    attestation_challenge,
                    algorithm,
                    version,
                    platform,
                    manufacturer,
                    model,
                    android_version,
                    display_name,
                    enabled,
                    created_at,
                    last_seen_at
                )
                VALUES (
                    :device_id,
                    :pc_identity_public,
                    :identity_public,
                    :device_public,
                    :hardware_public,
                    :identity_binding_signature,
                    :pairing_id,
                    :pairing_nonce,
                    :hardware_algorithm,
                    :hardware_security,
                    :attestation_challenge,
                    :algorithm,
                    :version,
                    :platform,
                    :manufacturer,
                    :model,
                    :android_version,
                    :display_name,
                    :enabled,
                    COALESCE(:created_at, CURRENT_TIMESTAMP),
                    :last_seen_at
                )
                ON CONFLICT(device_id) DO UPDATE SET
                    pc_identity_public = excluded.pc_identity_public,
                    identity_public = excluded.identity_public,
                    device_public = excluded.device_public,
                    hardware_public = excluded.hardware_public,
                    identity_binding_signature =
                        excluded.identity_binding_signature,
                    pairing_id = excluded.pairing_id,
                    pairing_nonce = excluded.pairing_nonce,
                    hardware_algorithm = excluded.hardware_algorithm,
                    hardware_security = excluded.hardware_security,
                    attestation_challenge = excluded.attestation_challenge,
                    algorithm = excluded.algorithm,
                    version = excluded.version,
                    platform = COALESCE(excluded.platform, trusted_devices.platform),
                    manufacturer = COALESCE(
                        excluded.manufacturer,
                        trusted_devices.manufacturer
                    ),
                    model = COALESCE(excluded.model, trusted_devices.model),
                    android_version = COALESCE(
                        excluded.android_version,
                        trusted_devices.android_version
                    ),
                    display_name = COALESCE(
                        excluded.display_name,
                        trusted_devices.display_name
                    ),
                    enabled = excluded.enabled,
                    last_seen_at = excluded.last_seen_at
                """,
                device,
            )

    def get_trusted_device(
        self,
        identity_public: str,
        device_public: str,
    ) -> dict[str, Any] | None:
        device_id = self.device_id(device_public)

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM trusted_devices
                WHERE device_id = ?
                  AND identity_public = ?
                  AND device_public = ?
                """,
                (device_id, identity_public, device_public),
            ).fetchone()

        return dict(row) if row is not None else None

    def list_trusted_devices(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM trusted_devices
                ORDER BY created_at ASC, device_id ASC
                """
            ).fetchall()

        return [dict(row) for row in rows]

    def remove_trusted_device(self, device_public: str) -> bool:
        device_id = self.device_id(device_public)

        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM trusted_devices
                WHERE device_id = ?
                """,
                (device_id,),
            )

        return cursor.rowcount > 0

    def mark_trusted_device_seen(self, device_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE trusted_devices
                SET last_seen_at = CURRENT_TIMESTAMP
                WHERE device_id = ?
                """,
                (device_id,),
            )

    @staticmethod
    def device_id(device_public: str) -> str:
        import hashlib

        digest = hashlib.sha256(
            device_public.encode("ascii")
        ).hexdigest()

        return "android-" + digest[:24]


# Backwards-compatible alias for code that wants a repository-style name.
TrustedDeviceRepository = LazyPCDatabase
