# config/settings.py

class ServerConfig:
    HOST = "0.0.0.0"
    PORT = 8000
    WS_PATH = "/ws"


class ScreenConfig:
    FPS = 7                      # кадров в секунду
    FRAME_DELAY = 1 / FPS        # автоматический расчёт


class MouseConfig:
    SENSITIVITY = 1.4            # для relative move
