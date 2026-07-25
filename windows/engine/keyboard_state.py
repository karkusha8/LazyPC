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