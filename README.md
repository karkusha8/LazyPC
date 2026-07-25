# LazyPC

<p align="center">
  <b>Remote desktop application for controlling a PC from Android</b>
</p>

LazyPC is a remote desktop application that allows users to control a computer remotely from an Android device.

The project focuses on low-latency communication, peer-to-peer networking, and responsive remote control.

---

## 🚧 Project Status

LazyPC is currently under active development.

Current MVP features:

- ✅ WebRTC peer-to-peer connection
- ✅ Real-time screen streaming
- ✅ High-quality video transmission
- ✅ Remote mouse control
- ✅ Mouse drag mode
- ✅ Scroll control
- ✅ Custom virtual keyboard
- ✅ Keyboard input transmission
---

## 🏗️ Architecture

LazyPC consists of three main components:

```
                 Signaling
Android Client ─────────── Server


                 WebRTC P2P
Android Client ─────────── Windows Agent
```

### Components

**LazyPC_android**
- Android application
- Displays remote screen
- Processes touch input
- Sends mouse and keyboard commands

**LazyPC_server**
- Signaling server
- Helps establish connections between devices

**LazyPC_windows**
- Desktop agent
- Captures screen
- Processes remote commands
- Handles mouse and keyboard input

---

## 🛠️ Technologies

### Android
- Kotlin
- Jetpack Compose
- WebRTC
- WebSocket

### Server
- Python
- AsyncIO
- WebSockets

### Windows
- Screen capture
- Input simulation
- Desktop interaction APIs
- Real-time data processing

---

## ✨ Key Features

### Real-time streaming
High-quality, low-latency screen transmission designed for interactive remote control.

### Peer-to-peer connection
Uses WebRTC to establish direct communication between devices.

### Custom control interface
LazyPC includes a custom mobile control system designed specifically for remote PC interaction:

- Custom virtual keyboard
- Touch-based mouse control
- Drag gestures
- Scroll gestures

### Remote input

Supports:
- Mouse movement tracking
- Mouse button actions
- Scroll control
- Drag operations
- Virtual keyboard input

---

## 🗺️ Roadmap

- [x] Basic remote connection
- [x] WebRTC communication
- [x] Screen streaming
- [x] Mouse and keyboard control

Future plans:

- [ ] Keyboard shortcuts
- [ ] Streaming optimization
- [ ] Connection stability improvements
- [ ] File transfer
- [ ] Audio streaming
- [ ] Stable public release

---

## 🎯 Motivation

LazyPC was created to explore technologies behind modern remote desktop applications:

- Real-time communication
- Peer-to-peer networking
- Low-latency streaming
- Cross-platform architecture

---

## 📸 Demo

A demonstration video will be added after completing the first stable MVP release.


