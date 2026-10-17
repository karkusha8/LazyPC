"""The PC's long-term Noise static key (X25519), protected at rest.

On Windows the private key is sealed with DPAPI (bound to the Windows user),
so copying the file to another machine or account yields nothing. On other
platforms (tests, Linux dev boxes) it falls back to a 0600 file and
`protected_by_os` is False.
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519

_ENTROPY = b"lazypc/pc-static/v4"
Protector = tuple[Callable[[bytes], bytes], Callable[[bytes], bytes]]


def _default_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / ".local" / "share"
    return base / "LazyPC"


def _dpapi() -> Protector:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    def blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def run(fn, data: bytes, *lead) -> bytes:
        src, keep1 = blob(data)
        ent, keep2 = blob(_ENTROPY)
        out = DATA_BLOB()
        ok = fn(ctypes.byref(src), *lead, ctypes.byref(ent), None, None, 0,
                ctypes.byref(out))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))
            del keep1, keep2

    def protect(data: bytes) -> bytes:
        return run(crypt32.CryptProtectData, data, "LazyPC")

    def unprotect(data: bytes) -> bytes:
        return run(crypt32.CryptUnprotectData, data, None)

    return protect, unprotect


def _platform_protector() -> tuple[Protector, bool]:
    if sys.platform == "win32":
        return _dpapi(), True
    return ((lambda b: b), (lambda b: b)), False


class PcIdentity:
    """Loads or creates the PC's Noise static key."""

    def __init__(self, directory: "str | Path | None" = None,
                 protector: "Protector | None" = None):
        self._dir = Path(directory) if directory else _default_dir()
        self._path = self._dir / "pc_static_v4.bin"
        if protector is None:
            protector, self.protected_by_os = _platform_protector()
        else:
            self.protected_by_os = True
        self._protect, self._unprotect = protector
        self._priv: "bytes | None" = None

    def ensure_created(self) -> None:
        if self._priv is not None:
            return
        if self._path.exists():
            raw = self._unprotect(self._path.read_bytes())
            if len(raw) != 32:
                raise RuntimeError("PC static key file is corrupt.")
            self._priv = raw
            return
        key = x25519.X25519PrivateKey.generate()
        raw = key.private_bytes(serialization.Encoding.Raw,
                                serialization.PrivateFormat.Raw,
                                serialization.NoEncryption())
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_bytes(self._protect(raw))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self._path)
        self._priv = raw

    def private_bytes(self) -> bytes:
        self.ensure_created()
        return self._priv  # type: ignore[return-value]

    def public_bytes(self) -> bytes:
        return x25519.X25519PrivateKey.from_private_bytes(
            self.private_bytes()).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def public_b64(self) -> str:
        return base64.b64encode(self.public_bytes()).decode("ascii")
