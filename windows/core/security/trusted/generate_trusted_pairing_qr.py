from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pairing_qr import create_pairing_qr, delete_pairing_qr
from security.trusted.link_runner import SignalingTransport, run_pairing
from security.trusted.trusted_pairing import TrustedPairingManager


OUTPUT = (
    Path(os.environ.get("LOCALAPPDATA", Path.home()))
    / "LazyPC"
    / "pairing"
    / "trusted_device_qr.png"
)


def load_transport() -> SignalingTransport:
    """Return YOUR signaling client.

    It must implement:
        async send(room: bytes, kind: str, data: bytes) -> None
        async recv(room: bytes) -> tuple[str, bytes]
    `room` is an opaque 16-byte mailbox id; `kind` is a short label; `data`
    is opaque bytes. See PROTOCOL.md for the wire format.
    """
    raise NotImplementedError(
        "Implement load_transport() with your signaling client "
        "(a SignalingTransport, see security/trusted/link_runner.py)."
    )


async def enter_phone_code(expected_code: str) -> bool:
    """Ask for the code shown on the phone and compare it locally on Windows.

    The expected code is deliberately never printed on the PC. This prevents
    the UI from turning the action into a meaningless accept/click-through.
    """
    print()
    print("[SECURITY] A pairing code is displayed on your phone.")
    print("[SECURITY] Enter that code here to continue. Do not guess it.")
    entered = await asyncio.to_thread(input, "Code shown on phone: ")
    if entered.strip() != expected_code:
        print("[SECURITY] Incorrect code. Pairing cancelled.")
        return False
    print("[SECURITY] Code accepted. Verifying phone key and attestation...")
    return True


async def main() -> None:
    manager = TrustedPairingManager()
    invitation, path = create_pairing_qr(manager, OUTPUT)

    print("=" * 60)
    print("LazyPC Trusted Device Pairing (v4)")
    print("=" * 60)
    print(f"[SECURITY] Expires in: {invitation.remaining():.0f} seconds")
    print(f"[SECURITY] QR image: {path}")
    print("[SECURITY] Scan this QR with the LazyPC Android app.")
    print("=" * 60)

    try:
        os.startfile(path)                # default Windows image viewer
    except (OSError, AttributeError) as error:
        print(f"[SECURITY] Could not open QR automatically: {error}")

    try:
        phone = await run_pairing(invitation.session, load_transport(),
                                  enter_phone_code)
        if phone is None:
            print("[SECURITY] Pairing did not complete.")
        else:
            print(f"[SECURITY] Paired: {phone.device_id}")
    finally:
        delete_pairing_qr(path)
        print("[SECURITY] QR image removed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SECURITY] Pairing generator stopped.")
