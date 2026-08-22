import asyncio

from connection.connection_manager import ConnectionManager


SIGNALING_URL = "ws://127.0.0.1:8000/ws"


async def main():

    manager = ConnectionManager(
        SIGNALING_URL
    )

    await manager.run()


if __name__ == "__main__":

    asyncio.run(
        main()
    )