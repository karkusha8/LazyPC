from __future__ import annotations

import os
from pathlib import Path
import time

from pairing_qr import create_pairing_qr, delete_pairing_qr
from security.trusted.trusted_pairing import TrustedPairingManager


OUTPUT = (
    Path(os.environ.get("LOCALAPPDATA", Path.home()))
    / "LazyPC"
    / "pairing"
    / "trusted_device_qr.png"
)


def main() -> None:
    manager = TrustedPairingManager()

    invitation, path = create_pairing_qr(
        manager,
        OUTPUT,
    )

    print("=" * 60)
    print("LazyPC Trusted Device Pairing")
    print("=" * 60)
    print("[SECURITY] Trusted Device pairing session created")
    print("[SECURITY] Expires in: 120 seconds")
    print(f"[SECURITY] QR image: {path}")
    print()
    print("[SECURITY] Scan this QR with the LazyPC Android app.")
    print("[SECURITY] QR payload generated")
    print("=" * 60)

    # Open the PNG with the default Windows image viewer.
    try:
        os.startfile(path)
    except OSError as error:
        print(f"[SECURITY] Could not open QR automatically: {error}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SECURITY] Pairing generator stopped.")
    finally:
        delete_pairing_qr(path)
        print("[SECURITY] QR image removed.")


if __name__ == "__main__":
    main()
