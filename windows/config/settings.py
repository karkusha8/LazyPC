# config/settings.py

class ServerConfig:
    HOST = "0.0.0.0"
    PORT = 8000
    WS_PATH = "/ws"


class ScreenConfig:
    FPS = 60
    OUTPUT_COLOR = "RGB"
    VIDEO_MODE = True
    FRAME_WAIT_DELAY = 0.001


class MouseConfig:
    SENSITIVITY = 1.4            # для relative move
