from __future__ import annotations

from security.common.pc_static import PcIdentity

from .pairing import TrustedDeviceStore
from .secure_link import (
    LibNoiseResponder,
    NoiseFactory,
    SessionContext,
    SessionGate,
    session_room,
)


class SessionAuthenticator:
    """Authenticates paired phones. Replaces AndroidAuthenticator and
    HardwareWebRTCAuthenticator (their two stages are now one signed
    transcript, bound to the connection).

    Usage per incoming connection:

        ctx = auth.accept(hello_bytes)            # LinkError -> drop silently
        answer_sdp = <build RTCPeerConnection answer from ctx.offer_sdp>
        reply_bytes = ctx.reply(answer_sdp)       # send back through signaling
        ... when the transport connects:
        ctx.assert_dtls_peer(actual_remote_dtls_fingerprint_bytes)
        ... when the `auth` DataChannel opens:
        challenge = ctx.begin_auth()              # send as JSON
        ... on the phone's response:
        auth.authorize(ctx, response_dict)        # LinkError -> close everything
        ... only now enable screen / input / files / audio-video.
    """

    def __init__(self, identity: "PcIdentity | None" = None,
                 store: "TrustedDeviceStore | None" = None,
                 noise_factory: NoiseFactory = LibNoiseResponder) -> None:
        self.identity = identity or PcIdentity()
        self.identity.ensure_created()
        self.store = store or TrustedDeviceStore(
            pc_static_pub=self.identity.public_bytes())
        self.gate = SessionGate(
            pc_static_priv=self.identity.private_bytes(),
            pc_static_pub=self.identity.public_bytes(),
            store=self.store,
            noise_factory=noise_factory,
        )

    @property
    def room(self) -> bytes:
        return session_room(self.identity.public_bytes())

    def accept(self, hello: bytes) -> SessionContext:
        return self.gate.accept(hello)

    def authorize(self, ctx: SessionContext, response: dict) -> dict:
        phone = ctx.verify_auth(response)
        if ctx.authorized:
            self.store.mark_seen(phone.device_id)
        return {"device_id": phone.device_id, "scope": response.get("scope")}
