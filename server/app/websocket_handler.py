from fastapi import WebSocket, WebSocketDisconnect

from app.models import PeerRole
from app.registry import registry
from app.relay import safe_close, safe_send_text


async def handle_connection(ws: WebSocket):
    await ws.accept()

    # A reconnect can close a socket before the old handler reaches its
    # receive loop. Treat that as a normal disconnect, not an ASGI error.
    try:
        hello = (await ws.receive_text()).strip()
    except WebSocketDisconnect:
        print("🔌 socket disconnected during handshake")
        return

    if hello == "HELLO_AGENT":
        role = PeerRole.AGENT
    elif hello == "HELLO_CLIENT":
        role = PeerRole.CLIENT
    else:
        print("❌ Unknown role:", hello)
        await safe_close(ws)
        return

    print(f"✅ {role.value} connected")

    previous = await registry.register(role, ws)

    if previous is not None and previous is not ws:
        await safe_close(previous)

    # IMPORTANT:
    # The signaling WebSocket is only a signaling transport. An Agent
    # connecting/reconnecting must NOT start a WebRTC session by itself.
    # A new WebRTC negotiation is requested by a CLIENT connection.
    if role == PeerRole.CLIENT:
        print("📱 Client connected -> requesting new session")
        await registry.notify_client_connected()
    else:
        print("🖥️ Agent signaling connected -> waiting for client")

    try:
        while True:
            msg = await ws.receive_text()
            print(f"📥 {role.value}: {msg[:80]}")

            peer = await registry.get_peer(role)
            if peer is None:
                continue

            ok = await safe_send_text(peer, msg)

            if ok:
                print(
                    f"📤 {role.value} -> "
                    f"{'client' if role == PeerRole.AGENT else 'agent'}"
                )

    except WebSocketDisconnect:
        print(f"🔌 {role.value} disconnected")

        # IMPORTANT:
        # Signaling disconnect does not mean that WebRTC is dead.
        # Do not send client_disconnected and do not destroy the Agent.

    finally:
        await registry.unregister(role, ws)