from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32

crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPVOID,
    ctypes.POINTER(DATA_BLOB),
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptProtectData.restype = wintypes.BOOL

crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(DATA_BLOB),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(DATA_BLOB),
    wintypes.LPVOID,
    ctypes.POINTER(DATA_BLOB),
    wintypes.DWORD,
    ctypes.POINTER(DATA_BLOB),
]
crypt32.CryptUnprotectData.restype = wintypes.BOOL

kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
kernel32.LocalFree.restype = wintypes.HLOCAL

CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _blob(data: bytes) -> DATA_BLOB:
    if not data:
        buffer = ctypes.create_string_buffer(b"\x00")
        return DATA_BLOB(0, ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))

    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )


def dpapi_protect(data: bytes) -> bytes:
    source = _blob(data)
    result = DATA_BLOB()

    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "LazyPC",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    ):
        raise ctypes.WinError()

    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)


def dpapi_unprotect(data: bytes) -> bytes:
    source = _blob(data)
    result = DATA_BLOB()
    description = wintypes.LPWSTR()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(source),
        ctypes.byref(description),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    ):
        raise ctypes.WinError()

    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
        if description:
            kernel32.LocalFree(description)


class ProtectedKeyStorage:
    """
    Stores private key material encrypted with Windows DPAPI.

    The encrypted blob is tied to the Windows user profile running the Agent.
    The private key is never written to disk in plaintext.
    """

    def __init__(self, app_name: str = "LazyPC") -> None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("LOCALAPPDATA is unavailable.")

        self.root = Path(local_app_data) / app_name / "security"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def save_keypair(
        self,
        name: str,
        private_key_der: bytes,
        public_key_der: bytes,
        algorithm: str,
        version: int = 1,
    ) -> None:
        payload = {
            "version": version,
            "algorithm": algorithm,
            "private_key_dpapi": base64.b64encode(
                dpapi_protect(private_key_der)
            ).decode("ascii"),
            "public_key": base64.b64encode(
                public_key_der
            ).decode("ascii"),
        }

        target = self._path(name)
        temp = target.with_suffix(".tmp")

        temp.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

        os.replace(temp, target)

    def load_keypair(self, name: str) -> tuple[bytes, bytes, str, int]:
        path = self._path(name)

        if not path.exists():
            raise FileNotFoundError(path)

        payload = json.loads(
            path.read_text(encoding="utf-8")
        )

        private_key = dpapi_unprotect(
            base64.b64decode(payload["private_key_dpapi"])
        )

        public_key = base64.b64decode(
            payload["public_key"]
        )

        return (
            private_key,
            public_key,
            payload["algorithm"],
            int(payload["version"]),
        )

    def exists(self, name: str) -> bool:
        return self._path(name).exists()

    def delete(self, name: str) -> None:
        self._path(name).unlink(missing_ok=True)