from __future__ import annotations

import os
from pathlib import Path

import qrcode

from security.trusted.trusted_pairing import PairingInvitation, TrustedPairingManager


DEFAULT_QR_PATH = (
    Path(os.environ.get("LOCALAPPDATA", Path.home()))
    / "LazyPC"
    / "pairing"
    / "trusted_device_qr.png"
)


def create_pairing_qr(
    manager: TrustedPairingManager,
    output_path: "str | Path" = DEFAULT_QR_PATH,
) -> tuple[PairingInvitation, Path]:
    """Create one pairing invitation and render its QR.

    The QR holds the pairing secret (PSK), so it must be shown only to the
    person holding the phone, and deleted as soon as pairing ends. The
    invitation's `session` is what must receive the pairing messages from
    signaling (link_runner.run_pairing).
    """
    invitation = manager.begin()

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    qrcode.make(invitation.qr_payload()).save(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass

    return invitation, path


def delete_pairing_qr(path: "str | Path" = DEFAULT_QR_PATH) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass
