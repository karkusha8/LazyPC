import asyncio

from agent import Agent


class ConnectionManager:

    def __init__(self, signaling_url: str):

        self.signaling_url = signaling_url

        self.agent = None

        self.running = True

    async def run(self):

        while self.running:

            try:

                print("=" * 40)
                print("[MANAGER] Starting Agent")
                print("=" * 40)

                self.agent = Agent(
                    self.signaling_url
                )

                await self.agent.start()

                #
                # Ждем пока Agent сообщит,
                # что соединение завершилось
                #

                await self.agent.wait_closed()

            except Exception as e:

                print(
                    "[MANAGER] Agent crashed:",
                    e
                )

            finally:

                if self.agent is not None:

                    try:

                        await self.agent.stop()

                    except Exception as e:

                        print(
                            "[MANAGER] Stop error:",
                            e
                        )

                    self.agent = None

            if not self.running:
                break

            print(
                "[MANAGER] Reconnecting in 2 seconds..."
            )

            await asyncio.sleep(2)

    async def stop(self):

        self.running = False

        if self.agent is not None:

            await self.agent.stop()