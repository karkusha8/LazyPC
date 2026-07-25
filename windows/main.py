import asyncio

from agent import Agent

SIGNALING_URL = "ws://127.0.0.1:8000/ws"


async def main():
    agent = Agent(SIGNALING_URL)

    try:
        await agent.start()

        print("[MAIN] Agent is running. Press Ctrl+C to stop.")

        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        pass

    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())