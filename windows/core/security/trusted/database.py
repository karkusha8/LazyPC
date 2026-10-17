from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class LazyPCDatabase:
    """Small synchronous SQLite database for persistent LazyPC state.

    v4 keeps ONE row per paired phone: its Noise static public key (identity on
    the wire) and its StrongBox public key (authorization). Only public keys
    are stored. The old `trusted_devices` table (3 keys + binding signatures)
    is left untouched; those pairings cannot be used by the v4 protocol and
    must be redone, after which `drop_legacy()` removes the old table.
    """

    DB_NAME = "lazypc.db"
    TABLE = "trusted_phones"
    LEGACY_TABLE = "trusted_devices"

    def __init__(self, path: "str | Path | None" = None) -> None:
        if path is None:
            local = os.environ.get("LOCALAPPDATA")
            if not local:
                raise RuntimeError("LOCALAPPDATA is unavailable.")
            path = Path(local) / "LazyPC" / self.DB_NAME
        self.path = Path(path)
        self.root = self.path.parent
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:                      # commit / rollback
                yield conn
        finally:
            conn.close()                    # `with conn` alone never closes

    def _initialize(self) -> None:
        with self._tx() as c:
            c.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE} (
                    device_id TEXT PRIMARY KEY,
                    phone_static BLOB NOT NULL UNIQUE,
                    hw_public BLOB NOT NULL,
                    pc_static BLOB NOT NULL,
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

    # ---------------------------------------------------------------- write
    def add_phone(self, device: dict[str, Any]) -> None:
        required = ("device_id", "phone_static", "hw_public", "pc_static")
        if not all(device.get(k) for k in required):
            raise ValueError("Incomplete trusted phone record.")
        row = {k: device.get(k) for k in (
            "device_id", "phone_static", "hw_public", "pc_static", "platform",
            "manufacturer", "model", "android_version", "display_name")}
        with self._tx() as c:
            c.execute(
                f"""
                INSERT INTO {self.TABLE} (
                    device_id, phone_static, hw_public, pc_static, platform,
                    manufacturer, model, android_version, display_name)
                VALUES (:device_id, :phone_static, :hw_public, :pc_static,
                        :platform, :manufacturer, :model, :android_version,
                        :display_name)
                ON CONFLICT(device_id) DO UPDATE SET
                    hw_public = excluded.hw_public,
                    pc_static = excluded.pc_static,
                    platform = COALESCE(excluded.platform, {self.TABLE}.platform),
                    manufacturer = COALESCE(excluded.manufacturer,
                                            {self.TABLE}.manufacturer),
                    model = COALESCE(excluded.model, {self.TABLE}.model),
                    android_version = COALESCE(excluded.android_version,
                                               {self.TABLE}.android_version),
                    enabled = 1
                """,
                row,
            )

    def remove(self, device_id: str) -> bool:
        with self._tx() as c:
            return c.execute(
                f"DELETE FROM {self.TABLE} WHERE device_id = ?", (device_id,)
            ).rowcount > 0

    def set_enabled(self, device_id: str, enabled: bool) -> bool:
        with self._tx() as c:
            return c.execute(
                f"UPDATE {self.TABLE} SET enabled = ? WHERE device_id = ?",
                (1 if enabled else 0, device_id),
            ).rowcount > 0

    def mark_seen(self, device_id: str) -> None:
        with self._tx() as c:
            c.execute(
                f"UPDATE {self.TABLE} SET last_seen_at = CURRENT_TIMESTAMP "
                "WHERE device_id = ?", (device_id,))

    # ----------------------------------------------------------------- read
    def find_by_static(self, phone_static: bytes) -> "dict[str, Any] | None":
        with self._tx() as c:
            row = c.execute(
                f"SELECT * FROM {self.TABLE} WHERE phone_static = ?",
                (phone_static,)).fetchone()
        return dict(row) if row is not None else None

    def list_phones(self) -> list[dict[str, Any]]:
        """Return JSON-safe display fields for the UI, never raw key material.

        Binary public keys remain available to the authentication path through
        find_by_static(); they are intentionally excluded from this listing.
        """
        with self._tx() as c:
            rows = c.execute(
                f"""
                SELECT device_id, platform, manufacturer, model, android_version,
                       display_name, enabled, created_at, last_seen_at
                FROM {self.TABLE}
                ORDER BY created_at, device_id
                """
            ).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- legacy
    def _legacy_exists(self, c: sqlite3.Connection) -> bool:
        return c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (self.LEGACY_TABLE,)).fetchone() is not None

    def legacy_count(self) -> int:
        with self._tx() as c:
            if not self._legacy_exists(c):
                return 0
            return c.execute(f"SELECT COUNT(*) FROM {self.LEGACY_TABLE}").fetchone()[0]

    def drop_legacy(self) -> None:
        with self._tx() as c:
            c.execute(f"DROP TABLE IF EXISTS {self.LEGACY_TABLE}")
