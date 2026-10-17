"""LazyPC secure link v4 (PC side).

Threat model: the signaling server is fully hostile. It can read, drop,
replay, reorder and rewrite everything it relays.

Layers
------
1. Noise over signaling.  SDP/ICE travel only inside Noise messages.
   * pairing : Noise_IKpsk2  (PC static from the QR, PSK from the QR)
   * sessions: Noise_IK      (both statics pinned at pairing)
   Unknown phone static key => the PC stays silent (no oracle, no WebRTC stack).
2. DTLS binding.  Both DTLS fingerprints are carried inside Noise, and the
   StrongBox signature below covers them, so a relay that terminates DTLS
   itself cannot produce a valid signature.
3. StrongBox signature over the full session transcript (Noise handshake hash,
   both statics, hw key, both DTLS fingerprints, fresh PC nonce, scope).
   The DataChannel stays "deaf" (only the `auth` label) until this succeeds.

The only third-party piece is the Noise library (`pip install noiseprotocol`),
isolated in LibNoiseResponder.  Everything else uses `cryptography`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, x25519

PROLOGUE = b"lazypc/v4"
NOISE_SESSION = b"Noise_IK_25519_ChaChaPoly_SHA256"
NOISE_PAIRING = b"Noise_IKpsk2_25519_ChaChaPoly_SHA256"

MAX_CLOCK_SKEW = 120.0       # seconds, phone clock vs PC clock
REPLAY_TTL = 300.0
AUTH_TTL = 15.0              # seconds to answer an auth challenge
PAIRING_TTL = 120.0
MAX_PAIRING_ATTEMPTS = 5
MAX_MSG = 64 * 1024


class LinkError(RuntimeError):
    """Any protocol failure. Callers drop the peer silently."""


# --------------------------------------------------------------------------
# Canonical encoding and transcripts
# --------------------------------------------------------------------------

def enc(*parts: bytes) -> bytes:
    """Length-prefixed concatenation: no delimiter ambiguity, ever."""
    out = bytearray()
    for p in parts:
        if not isinstance(p, (bytes, bytearray)):
            raise TypeError("transcript fields must be bytes")
        out += struct.pack(">I", len(p)) + bytes(p)
    return bytes(out)


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


_FP_RE = re.compile(
    r"^a=fingerprint:sha-256 ([0-9A-F]{2}(?::[0-9A-F]{2}){31})\s*$",
    re.M | re.I,
)


def sdp_fingerprint(sdp: str) -> bytes:
    """The single sha-256 DTLS fingerprint of an SDP (reject 0 or >1 distinct)."""
    found = {bytes.fromhex(m.replace(":", "")) for m in _FP_RE.findall(sdp)}
    if len(found) != 1:
        raise LinkError("SDP must contain exactly one sha-256 DTLS fingerprint")
    return found.pop()


def pairing_transcript(handshake_hash: bytes, pc_static: bytes,
                       phone_static: bytes, hw_public_der: bytes,
                       qr_nonce: bytes) -> bytes:
    return enc(b"LAZYPC/PAIR/v4", handshake_hash, pc_static, phone_static,
               hw_public_der, qr_nonce)


def session_transcript(scope: str, handshake_hash: bytes, pc_static: bytes,
                       phone_static: bytes, hw_public_der: bytes,
                       fp_pc: bytes, fp_phone: bytes, nonce: bytes,
                       session_id: bytes) -> bytes:
    return enc(b"LAZYPC/AUTH/v4", scope.encode("utf-8"), handshake_hash,
               pc_static, phone_static, hw_public_der, fp_pc, fp_phone,
               nonce, session_id)


def verify_p256(public_der: bytes, message: bytes, signature: bytes) -> None:
    try:
        key = serialization.load_der_public_key(public_der)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
                key.curve, ec.SECP256R1):
            raise LinkError("key is not P-256")
        key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except LinkError:
        raise
    except (InvalidSignature, ValueError) as exc:
        raise LinkError("invalid signature") from exc


def pairing_room(psk: bytes) -> bytes:
    """Signaling mailbox for one pairing. Derived from the QR secret, so the
    signaling server cannot guess or enumerate it."""
    return hashlib.sha256(b"lazypc/room/pair/v4" + psk).digest()[:16]


def session_room(pc_static_pub: bytes) -> bytes:
    """Signaling mailbox where a paired phone finds this PC."""
    return hashlib.sha256(b"lazypc/room/session/v4" + pc_static_pub).digest()[:16]


def generate_pc_static() -> tuple[bytes, bytes]:
    """New Noise static key for the PC -> (private, public), 32 bytes each.
    Store the private half with DPAPI / Credential Locker, never in SQLite."""
    priv = x25519.X25519PrivateKey.generate()
    return (
        priv.private_bytes(serialization.Encoding.Raw,
                           serialization.PrivateFormat.Raw,
                           serialization.NoEncryption()),
        priv.public_key().public_bytes(serialization.Encoding.Raw,
                                       serialization.PublicFormat.Raw),
    )


# --------------------------------------------------------------------------
# Noise adapter (the only place that touches the Noise library)
# --------------------------------------------------------------------------

class NoiseChannel(Protocol):
    remote_static: bytes
    handshake_hash: bytes

    def read_message(self, data: bytes) -> bytes: ...
    def write_message(self, payload: bytes) -> bytes: ...
    def encrypt(self, data: bytes) -> bytes: ...
    def decrypt(self, data: bytes) -> bytes: ...


NoiseFactory = Callable[[bytes, bytes, "bytes | None"], NoiseChannel]


class LibNoiseResponder:
    """Responder adapter for the noiseprotocol 0.3.x API.

    noiseprotocol does not expose a public remote-static getter. After the
    first handshake message is successfully read, the peer static key is held
    by the handshake state's ``rs`` field. This adapter isolates that
    version-specific access and validates the result before returning it.
    """

    def __init__(self, pattern: bytes, pc_priv: bytes, psk: "bytes | None" = None):
        from noise.connection import Keypair, NoiseConnection  # lazy import
        c = NoiseConnection.from_name(pattern)
        c.set_as_responder()
        c.set_keypair_from_private_bytes(Keypair.STATIC, pc_priv)
        c.set_prologue(PROLOGUE)
        if psk is not None:
            c.set_psks(psk)
        c.start_handshake()
        self._c = c
        self._remote_static: bytes | None = None

    @property
    def remote_static(self) -> bytes:
        """Return the authenticated remote X25519 static key from the handshake.

        ``noiseprotocol`` 0.3.x has no ``get_remote_public_key()`` method.
        Its NoiseConnection.read_message() processes the message through
        ``noise_protocol.handshake_state``; for IKpsk2 the decrypted remote
        static key is then stored as handshake state's ``rs`` value.
        """
        # Once the final handshake message is written, noiseprotocol calls
        # handshake_done() and may discard handshake_state. Cache the peer
        # static as soon as message 1 has been read, before writing pair2.
        if self._remote_static is not None:
            return self._remote_static

        protocol = getattr(self._c, "noise_protocol", None)
        if protocol is None:
            raise LinkError("Noise connection has no protocol state")

        # Support the field names used by noiseprotocol builds without ever
        # substituting the configured local key or a QR value for the peer key.
        state = getattr(protocol, "handshake_state", None)
        if state is None:
            state = getattr(protocol, "_handshake_state", None)
        if state is None:
            raise LinkError("Noise handshake state unavailable after reading pair1")

        remote = getattr(state, "rs", None)
        if remote is None:
            raise LinkError("Noise handshake did not yield a remote static key")

        # The default 25519 backend represents public keys as objects exposing
        # public_bytes; tolerate bytes-like values for alternate compatible
        # backends, but do not guess or serialize arbitrary objects.
        key = remote if isinstance(remote, (bytes, bytearray, memoryview)) else None
        if key is None:
            key = getattr(remote, "public_bytes", None)
            if callable(key):
                key = key()
        if not isinstance(key, (bytes, bytearray, memoryview)) or len(key) != 32:
            raise LinkError("Noise remote static key is not a valid 32-byte X25519 key")
        self._remote_static = bytes(key)
        return self._remote_static

    @property
    def handshake_hash(self) -> bytes:
        return bytes(self._c.get_handshake_hash())

    def read_message(self, data: bytes) -> bytes:
        return self._c.read_message(data)

    def write_message(self, payload: bytes) -> bytes:
        return self._c.write_message(payload)

    def encrypt(self, data: bytes) -> bytes:
        return self._c.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        return self._c.decrypt(data)


# --------------------------------------------------------------------------
# Trusted device registry (replace the 3-key schema with this one)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TrustedPhone:
    device_id: str
    phone_static: bytes      # Noise X25519 public key (identity on the wire)
    hw_public_der: bytes     # StrongBox P-256 SPKI DER (authorization key)
    enabled: bool = True


class PhoneStore(Protocol):
    def find(self, phone_static: bytes) -> "TrustedPhone | None": ...
    def add(self, phone: TrustedPhone, meta: dict) -> None: ...


class ReplayCache:
    def __init__(self, ttl: float = REPLAY_TTL):
        self._ttl = ttl
        self._seen: dict[bytes, float] = {}

    def check_and_add(self, key: bytes) -> bool:
        now = time.monotonic()
        for k in [k for k, t in self._seen.items() if now - t > self._ttl]:
            del self._seen[k]
        if key in self._seen:
            return False
        self._seen[key] = now
        return True


# --------------------------------------------------------------------------
# Pairing (QR) -- one invitation, Noise IKpsk2, StrongBox enrollment
# --------------------------------------------------------------------------

def _clean(value: Any) -> "str | None":
    return value[:64] if isinstance(value, str) else None


class PairingSession:
    """Lives only while the QR is on screen.

    The QR carries: PC static public key, 32-byte PSK, 32-byte nonce.
    The PSK is never sent over signaling; it only keys the Noise handshake,
    so a hostile signaling server cannot pair its own device or MITM pairing.
    The phone must create a FRESH StrongBox key whose attestation challenge
    is the QR nonce (proves the key was generated for this pairing).
    """

    def __init__(self, *, pc_static_priv: bytes, pc_static_pub: bytes,
                 store: PhoneStore,
                 verify_attestation: Callable[[bytes, list], Any],
                 noise_factory: NoiseFactory = LibNoiseResponder,
                 ttl: float = PAIRING_TTL):
        self._priv, self._pub = pc_static_priv, pc_static_pub
        self._store = store
        self._verify_attestation = verify_attestation
        self._factory = noise_factory
        self.psk = secrets.token_bytes(32)
        self.qr_nonce = secrets.token_bytes(32)
        self._deadline = time.monotonic() + ttl
        self._attempts = 0
        self._noise: "NoiseChannel | None" = None
        self._finished = False

    def qr_payload(self) -> str:
        return ("lazypc://pair/4?"
                f"pc={b64u(self._pub)}&psk={b64u(self.psk)}&n={b64u(self.qr_nonce)}")

    def remaining(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    @property
    def finished(self) -> bool:
        return self._finished or time.monotonic() > self._deadline

    def _alive(self) -> None:
        if self._finished or time.monotonic() > self._deadline:
            self._finished = True
            raise LinkError("pairing invitation is no longer valid")

    def handle_msg1(self, msg1: bytes) -> bytes:
        self._alive()
        if len(msg1) > MAX_MSG:
            raise LinkError("message too large")
        self._attempts += 1
        if self._attempts > MAX_PAIRING_ATTEMPTS:
            self._finished = True
            raise LinkError("too many pairing attempts")
        noise = self._factory(NOISE_PAIRING, self._priv, self.psk)
        try:
            noise.read_message(msg1)
            # Capture the initiator's static key while noiseprotocol still
            # retains the handshake state. Writing pair2 can finish IKpsk2
            # and clear that state in noiseprotocol 0.3.x.
            _ = noise.remote_static
            reply = noise.write_message(b'{"v":4}')
        except Exception as exc:
            raise LinkError("pairing handshake failed") from exc
        self._noise = noise
        return reply

    @property
    def sas(self) -> str:
        """Six-digit code derived from the completed pairing Noise handshake.

        The PC displays only an input prompt; the phone displays this same
        value. The person copies the code from phone to PC. This is an
        intentional-user-action check, not an independent cryptographic factor.
        Available only after handle_msg1() has successfully produced pair2.
        """
        if self._noise is None:
            raise LinkError("pairing handshake is not complete")
        n = int.from_bytes(hashlib.sha256(
            b"lazypc/sas" + self._noise.handshake_hash).digest()[:4], "big")
        return f"{n % 1_000_000:06d}"

    def code_accepted_proof(self) -> bytes:
        """Authenticate Windows' successful manual SAS-code check to Android.

        The QR PSK and completed Noise handshake hash bind this acknowledgement
        to this invitation. A signaling relay cannot forge it.
        """
        self._alive()
        if self._noise is None:
            raise LinkError("pairing handshake is not complete")
        return hmac.new(
            self.psk,
            b"LAZYPC/PAIR_CODE_ACCEPTED/v4" + self._noise.handshake_hash,
            hashlib.sha256,
        ).digest()

    def handle_enroll(self, ciphertext: bytes) -> "PendingEnrollment":
        self._alive()
        noise, self._noise = self._noise, None          # one enroll per handshake
        if noise is None or len(ciphertext) > MAX_MSG:
            raise LinkError("no handshake in progress")
        try:
            msg = json.loads(noise.decrypt(ciphertext))
            hw_der = b64d(msg["hw_public"])
            signature = b64d(msg["hw_signature"])
            chain = msg["attestation_chain"]
            if not isinstance(chain, list) or not chain:
                raise ValueError("bad chain")
        except Exception as exc:            # wrong PSK lands here too
            raise LinkError("bad enrollment message") from exc

        phone_static = noise.remote_static
        verify_p256(hw_der, pairing_transcript(
            noise.handshake_hash, self._pub, phone_static, hw_der,
            self.qr_nonce), signature)

        try:
            facts = self._verify_attestation(hw_der, chain)
        except Exception as exc:
            raise LinkError(f"attestation rejected: {exc}") from exc
        if not hmac.compare_digest(facts.attestation_challenge, self.qr_nonce):
            raise LinkError("attestation challenge is not this pairing's nonce")

        phone = TrustedPhone(
            device_id="android-" + hashlib.sha256(phone_static).hexdigest()[:24],
            phone_static=phone_static, hw_public_der=hw_der)
        meta = {k: _clean(msg.get(k)) for k in
                ("platform", "manufacturer", "model", "android_version")}
        return PendingEnrollment(self, noise, phone, meta)


class PendingEnrollment:
    """Enrollment whose Noise transcript and StrongBox attestation verified.

    The human input-code gate has already succeeded before pair3 is processed.
    """

    def __init__(self, session: PairingSession, noise: NoiseChannel,
                 phone: TrustedPhone, meta: dict):
        self._session, self._noise = session, noise
        self.phone, self.meta = phone, meta

    def approve(self) -> bytes:
        self._session._alive()
        self._session._finished = True
        self._session._store.add(self.phone, self.meta)
        return self._noise.encrypt(b'{"status":"PAIRED"}')

    def reject(self) -> bytes:
        self._session._finished = True
        return self._noise.encrypt(b'{"status":"REJECTED"}')


# --------------------------------------------------------------------------
# Sessions -- Noise IK, then the StrongBox challenge on the DataChannel
# --------------------------------------------------------------------------

class SessionGate:
    """One per PC. accept() is the only thing exposed to the signaling room."""

    def __init__(self, *, pc_static_priv: bytes, pc_static_pub: bytes,
                 store: PhoneStore,
                 noise_factory: NoiseFactory = LibNoiseResponder,
                 replay: "ReplayCache | None" = None):
        self._priv, self._pub = pc_static_priv, pc_static_pub
        self._store = store
        self._factory = noise_factory
        self._replay = replay or ReplayCache()

    def accept(self, msg1: bytes) -> "SessionContext":
        """Raises LinkError for anything not from a paired phone: stay silent."""
        if len(msg1) > MAX_MSG:
            raise LinkError("message too large")
        noise = self._factory(NOISE_SESSION, self._priv, None)
        try:
            payload = noise.read_message(msg1)
        except Exception as exc:
            raise LinkError("handshake failed") from exc
        phone = self._store.find(noise.remote_static)
        if phone is None or not phone.enabled:
            raise LinkError("unknown or disabled device")
        try:
            hello = json.loads(payload)
            ts, offer = float(hello["ts"]), str(hello["sdp"])
        except Exception as exc:
            raise LinkError("bad hello") from exc
        if abs(time.time() - ts) > MAX_CLOCK_SKEW:
            raise LinkError("stale hello")
        if not self._replay.check_and_add(hashlib.sha256(msg1).digest()):
            raise LinkError("replayed handshake")
        return SessionContext(noise, phone, self._pub, offer,
                              sdp_fingerprint(offer))


@dataclass
class _Pending:
    scope: str
    nonce: bytes
    session_id: bytes
    created: float


class SessionContext:
    """Per-connection state machine. Never shared, never global."""

    def __init__(self, noise: NoiseChannel, phone: TrustedPhone,
                 pc_static: bytes, offer_sdp: str, fp_phone: bytes):
        self._noise, self.phone, self._pc_static = noise, phone, pc_static
        self.offer_sdp, self.fp_phone = offer_sdp, fp_phone
        self.fp_pc: "bytes | None" = None
        self.handshake_hash: "bytes | None" = None
        self._pending: "_Pending | None" = None
        self._state = "OFFERED"          # OFFERED -> ANSWERED -> DEAD
        self.authorized = False

    def reply(self, answer_sdp: str) -> bytes:
        """Noise msg2 carrying the SDP answer. Build the answer first (with
        a non-trickle, fully gathered SDP), then call this."""
        if self._state != "OFFERED":
            raise LinkError("bad state")
        self.fp_pc = sdp_fingerprint(answer_sdp)
        msg2 = self._noise.write_message(
            json.dumps({"sdp": answer_sdp}).encode("utf-8"))
        self.handshake_hash = self._noise.handshake_hash
        self._state = "ANSWERED"
        return msg2

    def assert_dtls_peer(self, actual_fp: bytes) -> None:
        """Compare the DTLS certificate the stack really saw with the one the
        phone declared inside Noise. Call when the transport connects."""
        if not hmac.compare_digest(actual_fp, self.fp_phone):
            self._kill()
            raise LinkError("DTLS peer certificate differs from the Noise-declared one")

    def _kill(self) -> None:
        self._state, self.authorized, self._pending = "DEAD", False, None

    def begin_auth(self, scope: str = "session") -> dict:
        if self._state != "ANSWERED":
            raise LinkError("bad state")
        if scope != "session" and not self.authorized:
            raise LinkError("step-up requires an authorized session")
        self._pending = _Pending(scope, secrets.token_bytes(32),
                                 secrets.token_bytes(16), time.monotonic())
        return {"type": "auth_challenge", "scope": scope,
                "nonce": b64e(self._pending.nonce),
                "session_id": b64e(self._pending.session_id)}

    def verify_auth(self, msg: dict) -> TrustedPhone:
        """Single use: every call consumes the challenge, any failure kills
        the session (no retries on the same connection)."""
        if self._state != "ANSWERED":
            raise LinkError("bad state")
        p, self._pending = self._pending, None
        try:
            if p is None:
                raise LinkError("no pending challenge")
            if time.monotonic() - p.created > AUTH_TTL:
                raise LinkError("challenge expired")
            if msg.get("type") != "auth_response" or msg.get("scope") != p.scope:
                raise LinkError("unexpected message")
            if not hmac.compare_digest(b64d(msg["session_id"]), p.session_id):
                raise LinkError("session id mismatch")
            verify_p256(self.phone.hw_public_der, session_transcript(
                p.scope, self.handshake_hash, self._pc_static,
                self.phone.phone_static, self.phone.hw_public_der,
                self.fp_pc, self.fp_phone, p.nonce, p.session_id),
                b64d(msg["signature"]))
        except Exception as exc:
            self._kill()
            if isinstance(exc, LinkError):
                raise
            raise LinkError("malformed auth response") from exc
        if p.scope == "session":
            self.authorized = True
        return self.phone
