from __future__ import annotations

import os
from pathlib import Path
import qrcode

from security.trusted_pairing import TrustedPairingManager, PairingInvitation


DEFAULT_QR_PATH = (
    Path(os.environ.get("LOCALAPPDATA", Path.home()))
    / "LazyPC"
    / "pairing"
    / "trusted_device_qr.png"
)


def create_pairing_qr(
    manager: TrustedPairingManager,
    output_path: str | Path = DEFAULT_QR_PATH,
) -> tuple[PairingInvitation, Path]:
    """
    Create one Trusted Device pairing invitation and render its QR.

    IMPORTANT:
    The manager instance must be the same instance used by the running
    Agent for PAIR_RESPONSE verification. The QR is only the visual
    transport for the already-created one-time invitation.
    """
    invitation = manager.begin()
    payload = invitation.qr_payload()

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    image = qrcode.make(payload)
    image.save(path)

    return invitation, path


def delete_pairing_qr(path: str | Path = DEFAULT_QR_PATH) -> None:
    path = Path(path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
