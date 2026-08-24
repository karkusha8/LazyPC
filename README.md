# LazyPC

<p align="center">
  <b>Remote desktop application for controlling a PC from Android</b>
</p>

LazyPC is a remote desktop application that allows users to control a Windows PC remotely from an Android device.

The project focuses on low-latency communication, peer-to-peer networking, real-time screen streaming, and responsive touch-based remote control.

---

## 🚧 Project Status

LazyPC is currently under active development.

The core remote-control system is already functional. The current development stage is focused on polishing the existing interaction system and expanding the application with additional remote desktop features.

---

## ✨ Features

### Remote Desktop

- Real-time Windows screen streaming
- WebRTC peer-to-peer communication
- High-quality video transmission
- Low-latency remote interaction

### Mouse Control

- Mouse movement
- Tap
- Double tap
- Mouse button actions
- Drag mode
- Scroll
- Touch-based mouse control

### Touch Gestures

LazyPC uses a custom gesture engine designed specifically for controlling a desktop from a touchscreen.

Supported gestures:

- One-finger mouse movement
- Tap
- Double tap
- Drag
- Two-finger scroll
- Pinch-to-zoom
- Pan Mode
- One-finger movement in Pan Mode
- Two-finger scroll in Pan Mode

The gesture engine also attempts to determine the user's intent and distinguish between similar gestures, such as scrolling and zooming.

### Zoom & Pan

The remote screen can be zoomed using a two-finger pinch gesture.

The video viewport remains fixed while only the video content is transformed.

Zooming is performed around the position between the user's fingers.

When zoomed in, Pan Mode allows the user to navigate around the enlarged remote screen:

- One finger → move the image
- Two fingers → scroll
- Mouse interaction is temporarily blocked while moving the image
- Pan Mode can be cancelled using the on-screen control or the corresponding gesture

Mouse movement is also restricted to the currently visible part of the remote desktop while zoomed in.

### Keyboard

- Custom virtual keyboard
- Keyboard input transmission
- Basic keyboard shortcuts
- Copy
- Paste
- Cut
- Save

---

## 🗺️ Roadmap

### Completed

- [x] Basic remote connection
- [x] WebRTC peer-to-peer communication
- [x] Real-time screen streaming
- [x] High-quality video transmission
- [x] Custom video renderer
- [x] Fixed video viewport
- [x] Remote mouse control
- [x] Tap and double tap
- [x] Mouse drag mode
- [x] Two-finger scrolling
- [x] Pinch-to-zoom
- [x] Zoom centered around pinch position
- [x] Touch gesture intent recognition
- [x] Scroll / zoom separation
- [x] Pan Mode
- [x] One-finger movement in Pan Mode
- [x] Two-finger scrolling in Pan Mode
- [x] Zoom-aware mouse boundaries
- [x] Custom virtual keyboard
- [x] Keyboard input
- [x] Basic keyboard shortcuts
- [x] Audio streaming
- [x] Connection status indicator

### Planned

- [ ] Clipboard synchronization
- [ ] Performance statistics
- [ ] FPS monitoring
- [ ] Latency monitoring
- [ ] Automatic reconnection
- [ ] Remember previously connected devices
- [ ] Wake-on-LAN support
- [ ] Video quality settings
- [ ] Frame rate settings
- [ ] Additional keyboard layouts
- [ ] Improved tablet interface
- [ ] File transfer
- [ ] Multiple monitor support
- [ ] Adaptive streaming optimization
- [ ] Stable public release

---

## 🎯 Motivation

LazyPC was created to explore the technologies behind modern remote desktop applications:

- Real-time communication
- Peer-to-peer networking
- Low-latency video streaming
- Remote input handling
- Touch gesture processing
- Cross-platform architecture

The project is also an experiment in designing a remote desktop experience specifically for touchscreen devices.

---

## 📸 Demo

A demonstration video and screenshots will be added as the project reaches a more stable release.