import json

from fastapi import WebSocket, WebSocketDisconnect

from app.models import PeerRole
from app.registry import registry
from app.relay import safe_close, safe_send_text


def _pairing_message(text: str) -> bool:
    try:
        message = json.loads(text)
    except Exception:
        return False
    return (
        message.get("type") == "create_session"
        and bool(message.get("pairing_token"))
    )


def _is_pairing_hello(text: str) -> bool:
    return text.strip() == "HELLO_CLIENT_PAIRING"


async def handle_connection(ws: WebSocket):
    await ws.accept()

    role = None
    pairing_mode = False

    try:
        try:
            first = (await ws.receive_text()).strip()
        except WebSocketDisconnect:
            print("🔌 socket disconnected during handshake")
            return

        if first == "HELLO_AGENT":
            role = PeerRole.AGENT

        elif first == "HELLO_CLIENT":
            role = PeerRole.CLIENT
            pairing_mode = False

        elif _is_pairing_hello(first):
            # Pairing hello is a signaling protocol message. It is consumed
            # by the server and NEVER forwarded to Windows.
            role = PeerRole.CLIENT
            pairing_mode = True

        elif _pairing_message(first):
            # Compatibility with the current Android build: it may send the
            # pairing create_session as the first frame.
            role = PeerRole.CLIENT
            pairing_mode = True

        else:
            print("❌ Unknown role:", first)
            await safe_close(ws)
            return

        suffix = " [PAIRING]" if pairing_mode else ""
        print(f"✅ {role.value} connected{suffix}")

        previous = await registry.register(role, ws)
        if previous is not None and previous is not ws:
            await safe_close(previous)

        if role == PeerRole.CLIENT:
            if pairing_mode:
                print("📱 Pairing client connected -> waiting for pairing session")

                # If the first frame already contained the pairing request,
                # forward it immediately.
                if _pairing_message(first):
                    ok = await registry.forward_to_agent(first)
                    if ok:
                        print("📤 pairing create_session -> agent")
            else:
                print("📱 Client connected -> requesting normal session")
                await registry.notify_normal_client_connected()
        else:
            print("🖥️ Agent signaling connected -> waiting for client")

        while True:
            msg = await ws.receive_text()

            # Pairing hello is consumed locally. Never relay it to Windows.
            if role == PeerRole.CLIENT and _is_pairing_hello(msg):
                print("📥 client: HELLO_CLIENT_PAIRING (consumed)")
                pairing_mode = True
                continue

            print(f"📥 {role.value}: {msg[:160]}")

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
        print(f"🔌 {role.value if role is not None else 'unknown'} disconnected")

    finally:
        if role is not None:
            await registry.unregister(role, ws)
