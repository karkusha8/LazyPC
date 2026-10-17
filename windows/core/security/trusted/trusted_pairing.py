from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from security.common.pc_static import PcIdentity

from .attestation_verifier import AttestationPolicy, verify_attestation_chain
from .pairing import TrustedDeviceStore
from .secure_link import (
    LibNoiseResponder,
    NoiseFactory,
    PairingSession,
    pairing_room,
)


@dataclass(frozen=True)
class PairingInvitation:
    """One pairing attempt. `session` must be the same object that handles the
    pairing messages arriving from signaling (see link_runner.run_pairing)."""

    session: PairingSession
    room: bytes

    def qr_payload(self) -> str:
        return self.session.qr_payload()

    def remaining(self) -> float:
        return self.session.remaining()


class TrustedPairingManager:
    def __init__(
        self,
        identity: "PcIdentity | None" = None,
        store: "TrustedDeviceStore | None" = None,
        noise_factory: NoiseFactory = LibNoiseResponder,
        policy: AttestationPolicy = AttestationPolicy(),
        is_revoked: "Callable[[str], bool] | None" = None,
    ) -> None:
        self.identity = identity or PcIdentity()
        self.identity.ensure_created()
        self.store = store or TrustedDeviceStore(
            pc_static_pub=self.identity.public_bytes())
        self._noise_factory = noise_factory
        self.policy = policy
        self._is_revoked = is_revoked
        self._current: "PairingInvitation | None" = None

    def _verify_attestation(self, hardware_public_der: bytes, chain: list):
        # PairingSession only needs `.attestation_challenge` from the result.
        return verify_attestation_chain(
            hardware_public_der=hardware_public_der,
            attestation_chain_b64=chain,
            policy=self.policy,
            is_revoked=self._is_revoked,
        ).info

    def begin(self) -> PairingInvitation:
        """Start a new invitation; any previous one is abandoned."""
        session = PairingSession(
            pc_static_priv=self.identity.private_bytes(),
            pc_static_pub=self.identity.public_bytes(),
            store=self.store,
            verify_attestation=self._verify_attestation,
            noise_factory=self._noise_factory,
        )
        self._current = PairingInvitation(session, pairing_room(session.psk))
        return self._current

    @property
    def current(self) -> "PairingInvitation | None":
        return self._current
