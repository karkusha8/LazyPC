# LazyPC

<p align="center">
  <b>Remote desktop application for controlling a Windows PC from Android</b>
</p>

LazyPC is a remote desktop system that allows an Android device to securely connect to and control a Windows PC.

## 🚧 Project Status

LazyPC is actively under development.

The core remote desktop pipeline is functional: Android can connect to Windows through WebRTC, receive the desktop in real time, transmit audio, and control mouse and keyboard input.

Current work focuses on security hardening, Trusted Devices, connection management, persistent storage, and the native Windows UI.

## 🏗️ Architecture

- **Android client** — touchscreen remote-control application
- **Windows Agent** — desktop capture, input, sessions and security
- **Signaling Server** — connection establishment and signaling
- **Windows UI** — native interface for PC status, connections and Trusted Devices

The signaling server is not the media transport. WebRTC provides the real-time connection between Android and Windows.

## ✨ Features

### Remote Desktop
- WebRTC peer-to-peer communication
- Real-time Windows screen streaming
- H.264 video
- 60 FPS capture pipeline
- Hardware-accelerated H.264 encoding when available
- Real-time audio
- WASAPI loopback capture
- Opus audio encoding

### Mouse & Touch
- Mouse movement
- Tap and double tap
- Mouse buttons
- Drag mode
- Scroll
- Custom touch mouse control
- Two-finger scrolling
- Pinch-to-zoom
- Pan Mode
- Gesture intent recognition
- Scroll / zoom separation
- Zoom-aware mouse boundaries
- Synchronized remote cursor

### Keyboard
- Custom virtual keyboard
- Keyboard input transmission
- Basic shortcuts
- Copy / Paste / Cut / Save

### Connections
- Direct connection by PC ID
- PC online/offline status
- Unified connection state handling
- Immediate connection rejection handling
- Direct-ID connection errors
- One-time 9-digit authentication
- Trusted Device connections

### Windows UI
A native Windows UI has been added for PC-side management.

It currently provides:
- PC ID and status
- Connection status
- Trusted Device section
- Trusted Device pairing
- Trusted Device list received through local IPC

The UI does **not** access the security database directly.

The intended flow is:

`Windows UI → Local IPC → Windows Agent → SQLite`

When the UI starts it requests the current Trusted Device list. When pairing happens while the UI is open, the Agent can push the updated list immediately.

### Trusted Devices
- Explicit Trusted Device pairing
- Persistent Trusted Device storage
- Android identity and device keys
- PC identity binding
- Hardware-backed Android keys
- Android Key Attestation
- StrongBox verification when available
- Trusted Device removal on Android
- SQLite storage on Windows

## 🔐 Security

LazyPC separates ordinary authentication from persistent Trusted Device authentication.

The ordinary connection security implementation includes:
- Windows identity keys
- Android identity keys
- One-time 9-digit authentication secret
- Challenge-response
- Ephemeral key exchange
- Session key derivation
- Transcript binding
- Key confirmation
- Replay protection
- Rate limiting
- Session expiration

The 9-digit secret is transferred through an independent channel and is not sent through signaling.

Trusted Device pairing additionally verifies the Android hardware-backed key and Key Attestation when supported.

See `SECURITY.md` for the security architecture and roadmap.

## 💾 Persistent State

Trusted Devices are stored in:

`%LOCALAPPDATA%\LazyPC\lazypc.db`

Private keys are never stored in this database.

The UI receives persistent state through the Agent rather than reading SQLite directly.

## 🗺️ Roadmap

### Completed

- [x] Basic remote connection
- [x] WebRTC peer-to-peer communication
- [x] Real-time screen streaming
- [x] H.264 video
- [x] 60 FPS capture
- [x] Hardware-accelerated encoding
- [x] Audio streaming
- [x] WASAPI loopback
- [x] Opus encoding
- [x] Custom video renderer
- [x] Remote mouse control
- [x] Drag mode
- [x] Touch gesture engine
- [x] Two-finger scrolling
- [x] Pinch-to-zoom
- [x] Pan Mode
- [x] Custom virtual keyboard
- [x] Direct PC-ID connection
- [x] PC online/offline status
- [x] Unified connection state
- [x] Connection rejection handling
- [x] Windows identity keys
- [x] Android identity keys
- [x] One-time 9-digit authentication
- [x] Challenge-response
- [x] Ephemeral key exchange
- [x] Session key derivation
- [x] Transcript binding
- [x] Key confirmation
- [x] Replay protection
- [x] Rate limiting
- [x] Session expiration
- [x] Trusted Device pairing
- [x] Trusted Device persistent storage
- [x] Android hardware-backed key support
- [x] Android Key Attestation
- [x] StrongBox verification
- [x] Trusted Device removal on Android
- [x] Windows SQLite Trusted Device database
- [x] Native Windows UI
- [x] UI ↔ Agent IPC
- [x] Trusted Device list retrieval and live updates

### Planned

- [ ] Clipboard synchronization
- [ ] Performance statistics
- [ ] FPS monitoring
- [ ] Latency monitoring
- [ ] Automatic reconnection
- [ ] Better multi-device management
- [ ] Windows-side Trusted Device revoke
- [ ] Identity-key change detection and warnings
- [ ] Session key rotation
- [ ] Forward secrecy hardening
- [ ] Post-compromise recovery
- [ ] Wake-on-LAN
- [ ] Video quality settings
- [ ] Frame rate settings
- [ ] Adaptive streaming optimization
- [ ] Additional keyboard layouts
- [ ] Improved tablet interface
- [ ] File transfer
- [ ] Multiple monitor support
- [ ] Stable public release

### Security 2.0
- [ ] Key transparency
- [ ] Auditable identity-key history
- [ ] Post-quantum hybrid handshake
- [ ] Post-quantum ratcheting

## 🎯 Motivation

LazyPC is a practical remote desktop project and a learning project focused on modern real-time and secure communication.

It explores WebRTC, peer-to-peer networking, real-time media, remote input, touch gestures, cross-platform architecture, local IPC, persistent device management, public-key authentication, hardware-backed keys, attestation, replay protection and modern session-key design.

## 📸 Demo

A demonstration video and screenshots will be added as LazyPC approaches a stable public release.
