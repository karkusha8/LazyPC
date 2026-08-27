import struct

from core.engine.gesture_engine import GestureEngine
from core.engine.keyboard_state import KeyboardState

from core.network.protocol import (

    PACKET_TAP,
    PACKET_DOUBLE_TAP,
    PACKET_DRAG_START,
    PACKET_DRAG_MOVE,
    PACKET_DRAG_END,
    PACKET_MOVE,
    PACKET_RIGHT_CLICK,
    PACKET_SCROLL,

    PACKET_TEXT,
    PACKET_KEY,
    PACKET_SHORTCUT,
    PACKET_LANG_SET,
    PACKET_MODIFIER,
)


class GestureRouter:


    def __init__(

        self,

        engine: GestureEngine,

        keyboard: KeyboardState
    ):

        self.engine = engine

        self.keyboard = keyboard


        print(
            "[INPUT] GestureRouter initialized"
        )


    # ================================================================
    # ROUTE
    # ================================================================


    def route(

        self,

        packet_type: int,

        payload: bytes
    ):


        # ============================================================
        # MOUSE
        # ============================================================


        if packet_type == PACKET_MOVE:

            self._handle_move(
                payload
            )


        elif packet_type == PACKET_TAP:

            self.engine.tap()


        elif packet_type == PACKET_DOUBLE_TAP:

            self.engine.double_tap()


        elif packet_type == PACKET_RIGHT_CLICK:

            self.engine.right_tap()


        elif packet_type == PACKET_DRAG_START:

            self.engine.drag_start()


        elif packet_type == PACKET_DRAG_MOVE:

            self._handle_drag_move(
                payload
            )


        elif packet_type == PACKET_DRAG_END:

            self.engine.drag_end()


        elif packet_type == PACKET_SCROLL:

            self._handle_scroll(
                payload
            )


        # ============================================================
        # KEYBOARD TEXT
        # ============================================================


        elif packet_type == PACKET_TEXT:

            self._handle_text(
                payload
            )


        # ============================================================
        # KEYBOARD KEY
        # ============================================================


        elif packet_type == PACKET_KEY:

            self._handle_key(
                payload
            )


        # ============================================================
        # KEYBOARD SHORTCUT
        # ============================================================


        elif packet_type == PACKET_SHORTCUT:

            self._handle_shortcut(
                payload
            )


        # ============================================================
        # LANGUAGE
        # ============================================================


        elif packet_type == PACKET_LANG_SET:

            self._handle_language(
                payload
            )


        # ============================================================
        # KEYBOARD MODIFIER
        # ============================================================


        elif packet_type == PACKET_MODIFIER:

            self._handle_modifier(
                payload
            )


        # ============================================================
        # UNKNOWN
        # ============================================================


        else:

            print(

                f"[INPUT] UNKNOWN PACKET "

                f"0x{packet_type:02X}"
            )


    # ================================================================
    # MOVE
    # ================================================================


    def _handle_move(
        self,
        payload: bytes
    ):


        if len(payload) != 8:

            print(
                "[MOUSE] Invalid MOVE payload"
            )

            return


        dx, dy = struct.unpack(

            ">ff",

            payload
        )


        self.engine.move(
            dx,
            dy
        )


    # ================================================================
    # DRAG MOVE
    # ================================================================


    def _handle_drag_move(
        self,
        payload: bytes
    ):


        if len(payload) != 8:

            print(
                "[MOUSE] Invalid DRAG_MOVE payload"
            )

            return


        dx, dy = struct.unpack(

            ">ff",

            payload
        )


        self.engine.drag_move(
            dx,
            dy
        )


    # ================================================================
    # SCROLL
    # ================================================================


    def _handle_scroll(
        self,
        payload: bytes
    ):


        if len(payload) != 4:

            print(
                "[MOUSE] Invalid SCROLL payload"
            )

            return


        (dy,) = struct.unpack(

            ">f",

            payload
        )


        self.engine.scroll(
            dy
        )


    # ================================================================
    # TEXT
    # ================================================================


    def _handle_text(
        self,
        payload: bytes
    ):


        if not payload:

            return


        try:

            text = payload.decode(
                "utf-8"
            )


        except UnicodeDecodeError as e:

            print(
                "[KEYBOARD] Invalid UTF-8:",
                e
            )

            return


        print(
            f"[KEYBOARD] RX TEXT -> {text!r}"
        )


        self.keyboard.write_text(
            text
        )


    # ================================================================
    # KEY
    # ================================================================


    def _handle_key(
        self,
        payload: bytes
    ):


        if len(payload) != 1:

            print(
                "[KEYBOARD] Invalid KEY payload"
            )

            return


        key_id = payload[0]


        print(
            f"[KEYBOARD] RX KEY -> {key_id}"
        )


        self.keyboard.press_key(
            key_id
        )


    # ================================================================
    # SHORTCUT
    # ================================================================


    def _handle_shortcut(
        self,
        payload: bytes
    ):


        if len(payload) != 2:

            print(
                "[KEYBOARD] Invalid SHORTCUT payload"
            )

            return


        modifier_id = payload[0]

        key_id = payload[1]


        print(

            f"[KEYBOARD] RX SHORTCUT -> "

            f"modifier={modifier_id} "

            f"key={key_id}"
        )


        self.keyboard.shortcut(

            modifier_id,

            key_id
        )


    # ================================================================
    # LANGUAGE
    # ================================================================


    def _handle_language(
        self,
        payload: bytes
    ):


        if len(payload) != 1:

            print(
                "[KEYBOARD] Invalid LANGUAGE payload"
            )

            return


        language = payload[0]


        print(
            f"[KEYBOARD] RX LANGUAGE -> {language}"
        )


        self.keyboard.set_language(
            language
        )

    # ================================================================
    # MODIFIER
    # ================================================================


    def _handle_modifier(
        self,
        payload: bytes
    ):

        if len(payload) != 2:

            print(
                "[KEYBOARD] Invalid MODIFIER payload"
            )

            return


        key_id = payload[0]
        pressed = payload[1] == 1

        print(
            f"[KEYBOARD] RX MODIFIER -> {key_id} "
            f"{'DOWN' if pressed else 'UP'}"
        )

        self.keyboard.modifier(
            key_id,
            pressed
        )