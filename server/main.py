from fastapi import FastAPI, WebSocket
import uvicorn

from app.websocket_handler import handle_connection

app = FastAPI()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await handle_connection(ws)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
    )