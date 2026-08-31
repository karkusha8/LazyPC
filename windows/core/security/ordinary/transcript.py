from __future__ import annotations

import hashlib
import struct


TRANSCRIPT_DOMAIN = b"LAZYPC-ORDINARY-V2"


class TranscriptBuilder:
    """
    Canonical transcript builder for Ordinary V2.

    Every field is length-prefixed. This prevents ambiguity caused
    by concatenating variable-length values directly.
    """

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    # ================================================================
    # FIELD ENCODING
    # ================================================================

    @staticmethod
    def _encode_field(
        name: str,
        value: bytes,
    ) -> bytes:
        name_bytes = name.encode("ascii")

        if len(name_bytes) > 0xFFFF:
            raise ValueError("Transcript field name is too long.")

        if len(value) > 0xFFFFFFFF:
            raise ValueError("Transcript field value is too long.")

        return (
            struct.pack(">H", len(name_bytes))
            + name_bytes
            + struct.pack(">I", len(value))
            + value
        )

    # ================================================================
    # ADD FIELD
    # ================================================================

    def add_bytes(
        self,
        name: str,
        value: bytes,
    ) -> "TranscriptBuilder":
        if not isinstance(value, bytes):
            raise TypeError(
                f"Transcript field {name!r} must be bytes."
            )

        self._parts.append(
            self._encode_field(name, value)
        )

        return self

    def add_text(
        self,
        name: str,
        value: str,
    ) -> "TranscriptBuilder":
        if not isinstance(value, str):
            raise TypeError(
                f"Transcript field {name!r} must be str."
            )

        return self.add_bytes(
            name,
            value.encode("utf-8"),
        )

    # ================================================================
    # BUILD
    # ================================================================

    def build(self) -> bytes:
        """
        Return the canonical transcript bytes.

        The domain separator is part of the transcript and therefore
        part of every authentication signature / confirmation MAC.
        """

        body = b"".join(self._parts)

        return (
            TRANSCRIPT_DOMAIN
            + struct.pack(">I", len(self._parts))
            + body
        )

    # ================================================================
    # DIGEST
    # ================================================================

    def digest(self) -> bytes:
        """
        SHA-256 digest of the canonical transcript.

        The digest is convenient for signatures and key confirmation.
        """

        return hashlib.sha256(
            self.build()
        ).digest()