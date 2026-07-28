from fastapi import WebSocket, WebSocketDisconnect

from app.models import PeerRole
from app.registry import registry
from app.relay import safe_close, safe_send_text


async def handle_connection(ws: WebSocket):

    await ws.accept()

    hello = (await ws.receive_text()).strip()

    if hello == "HELLO_AGENT":
        role = PeerRole.AGENT

    elif hello == "HELLO_CLIENT":
        role = PeerRole.CLIENT

    else:
        print("❌ Unknown role:", hello)
        await ws.close()
        return

    print(f"✅ {role.value} connected")

    #
    # Если старая сторона ещё подключена —
    # отключаем её.
    #
    previous = await registry.register(role, ws)

    if previous is not None:
        await safe_close(previous)

    #
    # Android подключился после Agent —
    # сразу отправляем сохранённый Offer.
    #
    if role == PeerRole.CLIENT:

        offer = await registry.get_offer()

        if offer is not None:

            print("📨 SEND STORED OFFER")

            await safe_send_text(ws, offer)

    try:

        while True:

            msg = await ws.receive_text()

            print(f"📥 {role.value}: {msg[:80]}")

            #
            # Запоминаем последний Offer.
            #
            if (
                role == PeerRole.AGENT
                and '"type":"offer"' in msg.replace(" ", "")
            ):
                await registry.store_offer(msg)

                print("💾 OFFER STORED")

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

        if role == PeerRole.CLIENT:
            await registry.notify_client_disconnected()


    finally:

        await registry.unregister(role, ws)