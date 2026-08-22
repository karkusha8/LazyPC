from network.protocol import (
    LANG_EN,
    LANG_RU,
)


class KeyboardState:


    def __init__(
        self,
        backend
    ):

        self.backend = backend

        self.language = LANG_EN

        # Modifiers currently held on Windows.
        # This is used to guarantee KEY UP on disconnect.
        self._held_modifiers = set()

        print(
            "[KEYBOARD] KeyboardState initialized"
        )


    # ============================================================
    # LANGUAGE
    # ============================================================


    def set_language(
        self,
        language: int
    ):


        if language not in (
            LANG_EN,
            LANG_RU
        ):

            print(
                "[KEYBOARD] Invalid language:",
                language
            )

            return False


        print(
            f"[KEYBOARD] LANGUAGE REQUEST -> "
            f"{language}"
        )


        success = (
            self.backend.set_language(
                language
            )
        )


        if success:

            self.language = language


            print(
                f"[KEYBOARD] LANGUAGE ACTIVE -> "
                f"{self.language}"
            )


        return success


    # ============================================================
    # GET LANGUAGE
    # ============================================================


    def get_language(
        self
    ) -> int:

        return self.language


    # ============================================================
    # TEXT
    # ============================================================


    def write_text(
        self,
        text: str
    ):

        self.backend.write_text(
            text
        )


    # ============================================================
    # KEY
    # ============================================================


    def press_key(
        self,
        key_id: int
    ):

        self.backend.press_key_id(
            key_id
        )


    # ============================================================
    # SHORTCUT
    # ============================================================


    def shortcut(
        self,
        modifier_id: int,
        key_id: int
    ):

        self.backend.shortcut(

            modifier_id,

            key_id
        )


    # ============================================================
    # MODIFIER
    # ============================================================


    def modifier(
        self,
        key_id: int,
        pressed: bool
    ):

        if pressed:

            # Do not send duplicate KEY DOWN packets if the same
            # modifier is already held.
            if key_id in self._held_modifiers:
                return

            self._held_modifiers.add(key_id)

            self.backend.key_down(
                key_id
            )

            print(
                f"[KEYBOARD] KEY DOWN -> {key_id}"
            )

            return


        # KEY UP
        if key_id not in self._held_modifiers:
            return

        self._held_modifiers.discard(
            key_id
        )

        self.backend.key_up(
            key_id
        )

        print(
            f"[KEYBOARD] KEY UP -> {key_id}"
        )


    # ============================================================
    # RELEASE ALL HELD MODIFIERS
    # ============================================================


    def release_all(
        self
    ):

        if not self._held_modifiers:
            return

        held = list(
            self._held_modifiers
        )

        print(
            f"[KEYBOARD] RELEASE ALL -> {held}"
        )

        self._held_modifiers.clear()

        for key_id in held:

            try:

                self.backend.key_up(
                    key_id
                )

            except Exception as e:

                print(
                    "[KEYBOARD] Failed to release",
                    key_id,
                    ":",
                    e
                )