from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

app = FastAPI()

clients = {
    "agent": None,
    "client": None,
}

last_offer = None


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global last_offer

    await ws.accept()

    role_raw = (await ws.receive_text()).strip()

    print("ROLE:", role_raw)

    if role_raw == "HELLO_AGENT":
        role = "agent"

    elif role_raw == "HELLO_CLIENT":
        role = "client"

    else:
        print("Unknown role")
        await ws.close()
        return

    clients[role] = ws

    print(f"{role} connected")

    #
    # Если Offer уже существует —
    # сразу отправляем новому Android.
    #

    if role == "client" and last_offer:

        await ws.send_text(last_offer)

    try:

        while True:

            msg = await ws.receive_text()

            print(f"{role}: {msg[:80]}")

            #
            # Просто сохраняем Offer.
            #

            if (
                role == "agent"
                and '"type":"offer"' in msg.replace(" ", "")
            ):
                last_offer = msg

            target = (
                "client"
                if role == "agent"
                else "agent"
            )

            peer = clients.get(target)

            if peer is None:
                continue

            #
            # Никакого анализа JSON.
            # Никаких candidate.
            # Просто пересылаем.
            #

            await peer.send_text(msg)

    except WebSocketDisconnect:

        print(f"{role} disconnected")

        clients[role] = None


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
    )