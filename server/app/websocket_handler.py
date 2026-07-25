from fastapi import WebSocket, WebSocketDisconnect

clients = {
    "agent": None,
    "client": None
}

last_offer = None


async def handle_connection(ws: WebSocket):
    global last_offer

    await ws.accept()

    role = (await ws.receive_text()).strip()
    print("ROLE:", role)

    if role not in ["HELLO_AGENT", "HELLO_CLIENT"]:
        await ws.close()
        return

    role = "agent" if role == "HELLO_AGENT" else "client"
    clients[role] = ws

    print(f"✅ {role} connected")

    # 🔥 если клиент подключился — отправляем сохраненный offer
    if role == "client" and last_offer:
        print("📨 SEND STORED OFFER TO CLIENT")
        await ws.send_text(last_offer)

    try:
        while True:
            msg = await ws.receive_text()
            print(f"📥 {role}:", msg[:60])

            # 🔥 сохраняем offer
            if role == "agent" and '"type": "offer"' in msg:
                last_offer = msg
                print("💾 OFFER STORED")

            # отправка другому
            target = "client" if role == "agent" else "agent"
            peer = clients.get(target)

            if peer:
                await peer.send_text(msg)
                print(f"📤 {role} → {target}")

    except WebSocketDisconnect:
        print(f"🔌 {role} disconnected")
        clients[role] = None