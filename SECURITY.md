# LazyPC Security Roadmap

This document describes the current security architecture and the planned evolution of LazyPC.

The design separates **identity**, **authentication**, **session key establishment**, and **Trusted Device persistence**.

---

## 1. Current Security Stage

### Identity
- [x] Windows identity key
- [x] Android identity key
- [x] Persistent identity storage
- [x] Identity-based device binding

### Ordinary Authentication
- [x] One-time 9-digit authentication secret
- [x] Challenge-response
- [x] Ephemeral key exchange
- [x] Session key derivation
- [x] Transcript binding
- [x] Key confirmation
- [x] Replay protection
- [x] Session expiration
- [x] Rate limiting / limited attempts

### Trusted Device
- [x] Explicit Trusted Device pairing
- [x] Android identity registration
- [x] Per-device key registration
- [x] PC identity binding
- [x] Hardware-backed key support
- [x] Android Key Attestation verification
- [x] StrongBox verification
- [x] Persistent Trusted Device storage
- [x] Trusted Device removal on Android

### Infrastructure
- [x] SQLite Trusted Device database on Windows
- [x] Windows UI ↔ Agent local IPC
- [x] UI obtains security state through the Agent

---

## 2. Target Security Architecture

`IDENTITY`
→ `Authentication`
→ `Ephemeral Key Exchange`
→ `Session Key`
→ `Key Confirmation`
→ `WebRTC`

Identity keys authenticate devices.

Ephemeral keys establish session-specific cryptographic material.

Long-term identity keys are not intended to become direct session encryption keys.

---

## 3. Signaling Trust Model

The signaling server is treated as potentially hostile transport.

It may observe, reorder, replay, or interfere with signaling messages and attempt public-key substitution.

Authentication therefore must not depend on the signaling server being trusted with private keys or the independent authentication secret.

The signaling server establishes connectivity; it is not the root of trust.

---

## 4. Ordinary Connection

Android proves both:

1. possession of the Android identity private key;
2. knowledge of the one-time 9-digit authentication secret.

The secret is transferred through an independent channel and is **not sent through signaling**.

The secret is not itself used directly as a session encryption key.

The authentication proof is bound to the current connection and its session-specific cryptographic state.

---

## 5. Transcript Binding

Proofs must be tied to the exact handshake in which they were created.

The transcript includes the parameters required to prevent cross-session proof reuse, including:

- protocol version;
- session ID;
- PC identity;
- Android identity;
- ephemeral public keys;
- nonce/challenge;
- other negotiated security parameters where applicable.

---

## 6. Key Confirmation

After deriving the session secret, both sides must cryptographically confirm that they derived the same result.

Only after successful confirmation should the connection transition into the fully authorized state.

---

## 7. Replay Protection

Old authentication material must not be accepted for a new connection.

The implementation uses session-specific state such as:

- unique session IDs;
- fresh challenges/nonces;
- ephemeral keys;
- handshake state;
- expiration;
- attempt limits.

---

## 8. Trusted Devices

Trusted Device is separate from ordinary authentication.

Pairing is an explicit enrollment operation.

During pairing Windows verifies:

- Android identity ownership;
- device-key ownership;
- PC identity binding;
- hardware-backed key information;
- Android Key Attestation.

The resulting Trusted Device record is persisted locally on Windows.

On future connections the Agent can challenge the trusted Android device and verify signatures using the stored public keys.

---

## 9. Hardware-backed Android Keys

When supported, LazyPC uses Android hardware-backed cryptographic keys.

StrongBox is preferred for the Trusted Device hardware key.

Android Key Attestation is verified during enrollment.

The attestation information is associated with the enrolled Trusted Device.

---

## 10. Trusted Device Database

Trusted Device records are stored in SQLite on Windows.

Records include information such as:

- PC identity public key
- Android identity public key
- Android device public key
- hardware public key
- identity binding signature
- pairing ID
- pairing nonce
- hardware algorithm
- hardware security level
- attestation challenge
- protocol version
- Android platform metadata
- manufacturer
- model
- Android version
- display name
- enabled state
- creation time
- last-seen time

**Private keys are never stored in the database.**

The UI does not directly access SQLite.

Architecture:

`UI → Local IPC → Windows Agent → SQLite`

---

## 11. Trusted Device Lifecycle

`Pair → Store → Authenticate → Use → Revoke`

Pairing creates a persistent trust relationship.

Trusted Device removal is already supported on Android. Windows-side revocation and more advanced lifecycle management remain planned.

---

## 12. Security Roadmap

### Next Level
- [ ] Identity-key change detection
- [ ] Windows Trusted Device revoke
- [ ] Better multi-device key management
- [ ] Forward secrecy hardening
- [ ] Session key rotation
- [ ] Post-compromise recovery

### Security 2.0

#### Key Transparency
- [ ] Key transparency
- [ ] Auditable identity-key history
- [ ] Detection of inconsistent identity keys presented by infrastructure

#### Post-Quantum
Future model:

`Classical DH + Post-Quantum KEM`
→ `Hybrid Session Key`

Planned:
- [ ] Post-quantum hybrid handshake
- [ ] Post-quantum ratcheting

Established standards and audited libraries should be used rather than custom cryptographic primitives.

---

## 13. Core Principles

- Signaling is treated as potentially hostile.
- Identity private keys never leave their devices.
- The one-time 9-digit secret is transferred outside signaling.
- The one-time secret is not used directly as a session encryption key.
- Authentication proofs are bound to the current session.
- Identity keys authenticate devices.
- Ephemeral keys establish session-specific cryptographic material.
- Session keys are separate from long-term identity keys.
- Trusted Device is a separate persistent trust mechanism.
- Private cryptographic material is never stored in the Trusted Device SQLite database.
- Security decisions remain in the Windows Agent rather than the UI.
- Cryptographic primitives should come from established libraries.
