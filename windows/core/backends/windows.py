import ctypes
from ctypes import wintypes

import pyautogui


# ================================================================
# WINDOWS CONSTANTS
# ================================================================

WM_INPUTLANGCHANGEREQUEST = 0x0050
HWND_BROADCAST = 0xFFFF

INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK = {
    "ctrl": 0x11,
    "alt": 0x12,
    "shift": 0x10,

    "tab": 0x09,
    "enter": 0x0D,
    "backspace": 0x08,
    "esc": 0x1B,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "f4": 0x73,
    "f5": 0x74,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,

    "a": 0x41,
    "b": 0x42,
    "c": 0x43,
    "d": 0x44,
    "e": 0x45,
    "f": 0x46,
    "g": 0x47,
    "h": 0x48,
    "i": 0x49,
    "j": 0x4A,
    "k": 0x4B,
    "l": 0x4C,
    "m": 0x4D,
    "n": 0x4E,
    "o": 0x4F,
    "p": 0x50,
    "q": 0x51,
    "r": 0x52,
    "s": 0x53,
    "t": 0x54,
    "u": 0x55,
    "v": 0x56,
    "w": 0x57,
    "x": 0x58,
    "y": 0x59,
    "z": 0x5A,
}


# ================================================================
# WINDOWS KEYBOARD LAYOUTS
# ================================================================

LANGUAGE_LAYOUTS = {
    0: "00000409",
    1: "00000419",
}


# ================================================================
# WINDOWS TYPES
# ================================================================

if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong


# ================================================================
# SENDINPUT STRUCTURES
# ================================================================


class KEYBDINPUT(ctypes.Structure):

    _fields_ = [

        (
            "wVk",
            wintypes.WORD
        ),

        (
            "wScan",
            wintypes.WORD
        ),

        (
            "dwFlags",
            wintypes.DWORD
        ),

        (
            "time",
            wintypes.DWORD
        ),

        (
            "dwExtraInfo",
            ULONG_PTR
        ),
    ]


class MOUSEINPUT(ctypes.Structure):

    _fields_ = [

        (
            "dx",
            wintypes.LONG
        ),

        (
            "dy",
            wintypes.LONG
        ),

        (
            "mouseData",
            wintypes.DWORD
        ),

        (
            "dwFlags",
            wintypes.DWORD
        ),

        (
            "time",
            wintypes.DWORD
        ),

        (
            "dwExtraInfo",
            ULONG_PTR
        ),
    ]


class HARDWAREINPUT(ctypes.Structure):

    _fields_ = [

        (
            "uMsg",
            wintypes.DWORD
        ),

        (
            "wParamL",
            wintypes.WORD
        ),

        (
            "wParamH",
            wintypes.WORD
        ),
    ]


class INPUT_UNION(ctypes.Union):

    _fields_ = [

        (
            "mi",
            MOUSEINPUT
        ),

        (
            "ki",
            KEYBDINPUT
        ),

        (
            "hi",
            HARDWAREINPUT
        ),
    ]


class INPUT(ctypes.Structure):

    _anonymous_ = (
        "union",
    )

    _fields_ = [

        (
            "type",
            wintypes.DWORD
        ),

        (
            "union",
            INPUT_UNION
        ),
    ]


# ================================================================
# ANDROID KEY ID ORDINALS
# ================================================================


KEY_ID_NAMES = [

    "a", "b", "c", "d", "e", "f", "g",
    "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s",
    "t", "u", "v", "w", "x", "y", "z",

    "slavic_1",
    "slavic_2",
    "slavic_3",
    "slavic_4",
    "slavic_5",
    "slavic_6",
    "slavic_7",

    "0", "1", "2", "3", "4",
    "5", "6", "7", "8", "9",

    "@",
    "#",
    "$",
    "%",
    "[",
    "]",
    "{",
    "}",
    "(",
    ")",
    "=",
    "<",
    ">",
    "_",
    ":",
    ";",
    "-",
    "+",
    "\\",
    "|",
    "?",
    ".",
    ",",
    "/",

    "space",
    "enter",
    "backspace",
    "tab",
    "shift",
    "esc",

    "ctrl",
    "alt",
    "win",

    "delete",

    "left",
    "right",
    "up",
    "down",

    "home",
    "end",

    "f5",
    "f9",
    "f10",
    "f11",

    "copy",
    "paste",
    "cut",
    "undo",
    "redo",
    "select_all",

    "alt_tab",
    "alt_f4",
    "ctrl_alt_del",
    "task_manager",
    "win_lock",
    "win_run",

    "switch_text",
    "switch_symbols",
    "switch_dev",
    "save",
    "switch_code",
    "f4",
    "switch_sys",
    "quote",
]


# ================================================================
# MODIFIER ORDINALS
# ================================================================


MODIFIER_NAMES = {

    71: "shift",

    73: "ctrl",

    74: "alt",
}


class WindowsBackend:


    def __init__(
        self
    ):


        pyautogui.PAUSE = 0

        pyautogui.FAILSAFE = False


        self.user32 = ctypes.WinDLL(

            "user32",

            use_last_error=True
        )


        # ========================================================
        # SENDINPUT SIGNATURE
        # ========================================================


        self.user32.SendInput.argtypes = [

            wintypes.UINT,

            ctypes.POINTER(INPUT),

            ctypes.c_int,
        ]


        self.user32.SendInput.restype = (

            wintypes.UINT
        )


        print(
            "[INPUT] WindowsBackend initialized"
        )


        print(

            f"[INPUT] INPUT structure size: "

            f"{ctypes.sizeof(INPUT)} bytes"
        )


    # ============================================================
    # CURSOR POSITION
    # ============================================================


    def get_cursor_position_normalized(
        self
    ):


        point = (

            wintypes.POINT()
        )


        success = (

            self.user32.GetCursorPos(

                ctypes.byref(
                    point
                )
            )
        )


        if not success:

            return None


        # ========================================================
        # VIRTUAL DESKTOP
        # ========================================================


        SM_XVIRTUALSCREEN = 76

        SM_YVIRTUALSCREEN = 77

        SM_CXVIRTUALSCREEN = 78

        SM_CYVIRTUALSCREEN = 79


        desktop_x = (

            self.user32.GetSystemMetrics(

                SM_XVIRTUALSCREEN
            )
        )


        desktop_y = (

            self.user32.GetSystemMetrics(

                SM_YVIRTUALSCREEN
            )
        )


        desktop_width = (

            self.user32.GetSystemMetrics(

                SM_CXVIRTUALSCREEN
            )
        )


        desktop_height = (

            self.user32.GetSystemMetrics(

                SM_CYVIRTUALSCREEN
            )
        )


        if (

            desktop_width <= 1

            or

            desktop_height <= 1

        ):

            return None


        normalized_x = (

            point.x - desktop_x

        ) / float(

            desktop_width - 1
        )


        normalized_y = (

            point.y - desktop_y

        ) / float(

            desktop_height - 1
        )


        normalized_x = max(

            0.0,

            min(
                1.0,
                normalized_x
            )
        )


        normalized_y = max(

            0.0,

            min(
                1.0,
                normalized_y
            )
        )


        return (

            normalized_x,

            normalized_y
        )


    # ============================================================
    # MOUSE MOVE
    # ============================================================


    def move(

        self,

        dx: float,

        dy: float
    ):


        pyautogui.moveRel(

            int(dx),

            int(dy),

            duration=0
        )


    # ============================================================
    # DRAG
    # ============================================================


    def drag(

        self,

        dx: float,

        dy: float
    ):


        pyautogui.moveRel(

            int(dx),

            int(dy),

            duration=0
        )


    # ============================================================
    # CLICK
    # ============================================================


    def click(

        self,

        button: str = "left"
    ):


        pyautogui.click(

            button=button
        )


    # ============================================================
    # MOUSE DOWN
    # ============================================================


    def mouse_down(

        self,

        button: str
    ):


        pyautogui.mouseDown(

            button=button
        )


    # ============================================================
    # MOUSE UP
    # ============================================================


    def mouse_up(

        self,

        button: str
    ):


        pyautogui.mouseUp(

            button=button
        )


    # ============================================================
    # SCROLL
    # ============================================================


    def scroll(

        self,

        dy: int
    ):


        pyautogui.scroll(
            dy
        )


    # ============================================================
    # TEXT
    # ============================================================


    def write_text(

        self,

        text: str
    ):


        if not text:

            return


        print(

            f"[KEYBOARD] TEXT -> {text!r}"
        )


        try:


            self._write_unicode(
                text
            )


        except Exception as e:


            print(

                "[KEYBOARD] Unicode input error:",

                e
            )


    # ============================================================
    # SEND ONE INPUT
    # ============================================================


    def _send_input(

        self,

        input_event: INPUT
    ):


        ctypes.set_last_error(0)


        sent = (

            self.user32.SendInput(

                1,

                ctypes.byref(
                    input_event
                ),

                ctypes.sizeof(INPUT)
            )
        )


        if sent != 1:


            error_code = (

                ctypes.get_last_error()
            )


            raise ctypes.WinError(

                error_code
            )

    def _key_down_vk(self, vk):

        inp = INPUT()
        inp.type = INPUT_KEYBOARD

        inp.ki = KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=0,
            time=0,
            dwExtraInfo=0
        )

        self._send_input(inp)

    def _key_up_vk(self, vk):

        inp = INPUT()
        inp.type = INPUT_KEYBOARD

        inp.ki = KEYBDINPUT(
            wVk=vk,
            wScan=0,
            dwFlags=KEYEVENTF_KEYUP,
            time=0,
            dwExtraInfo=0
        )

        self._send_input(inp)

    def _press_vk(self, vk):

        self._key_down_vk(vk)
        self._key_up_vk(vk)

    # Public keyboard primitives used by KeyboardState.
    # Keep these as thin wrappers around the existing SendInput path.
    def key_down(self, key_id: int):
        self._key_down_vk(self._vk_for_key_id(key_id))

    def key_up(self, key_id: int):
        self._key_up_vk(self._vk_for_key_id(key_id))

    def _vk_for_key_id(self, key_id: int):
        if key_id < 0 or key_id >= len(KEY_ID_NAMES):
            raise ValueError(f"Unknown KeyId: {key_id}")

        key = KEY_ID_NAMES[key_id]
        vk = VK.get(key)

        if vk is None:
            raise ValueError(f"Unsupported key: {key}")

        return vk

    # Public keyboard primitives used by KeyboardState.
    # KeyboardState calls these for held keys/modifiers.
    def key_down(self, key_id: int):
        vk = self._vk_for_key_id(key_id)
        self._key_down_vk(vk)

    def key_up(self, key_id: int):
        vk = self._vk_for_key_id(key_id)
        self._key_up_vk(vk)

    def _vk_for_key_id(self, key_id: int):
        if key_id < 0 or key_id >= len(KEY_ID_NAMES):
            raise ValueError(f"Unknown KeyId: {key_id}")

        key = KEY_ID_NAMES[key_id]
        vk = VK.get(key)

        if vk is None:
            raise ValueError(f"Unsupported key: {key}")

        return vk

    # ============================================================
    # UNICODE TEXT VIA SENDINPUT
    # ============================================================


    def _write_unicode(

        self,

        text: str
    ):


        utf16_data = text.encode(

            "utf-16-le"
        )


        for index in range(

            0,

            len(utf16_data),

            2
        ):


            code_unit = int.from_bytes(

                utf16_data[index:index + 2],

                byteorder="little"
            )


            key_down = INPUT()

            key_down.type = INPUT_KEYBOARD


            key_down.ki = KEYBDINPUT(

                wVk=0,

                wScan=code_unit,

                dwFlags=KEYEVENTF_UNICODE,

                time=0,

                dwExtraInfo=0
            )


            key_up = INPUT()

            key_up.type = INPUT_KEYBOARD


            key_up.ki = KEYBDINPUT(

                wVk=0,

                wScan=code_unit,

                dwFlags=(

                    KEYEVENTF_UNICODE

                    |

                    KEYEVENTF_KEYUP
                ),

                time=0,

                dwExtraInfo=0
            )


            self._send_input(
                key_down
            )


            self._send_input(
                key_up
            )


    # ============================================================
    # KEY
    # ============================================================


    def press_key_id(

        self,

        key_id: int
    ):


        if (

            key_id < 0

            or

            key_id >= len(KEY_ID_NAMES)

        ):


            print(

                f"[KEYBOARD] Unknown KeyId: {key_id}"
            )


            return


        key = (

            KEY_ID_NAMES[
                key_id
            ]
        )


        print(

            f"[KEYBOARD] KEY -> {key}"
        )


        normal_keys = {

            "space",

            "enter",

            "backspace",

            "tab",

            "shift",

            "esc",

            "ctrl",

            "alt",

            "delete",

            "left",

            "right",

            "up",

            "down",

            "home",

            "end",

            "f4",

            "f5",

            "f9",

            "f10",

            "f11",
        }


        if key in normal_keys:


            pyautogui.press(
                key
            )


            return


        if key == "copy":

            pyautogui.hotkey(
                "ctrl",
                "c"
            )


        elif key == "paste":

            pyautogui.hotkey(
                "ctrl",
                "v"
            )


        elif key == "cut":

            pyautogui.hotkey(
                "ctrl",
                "x"
            )


        elif key == "undo":

            pyautogui.hotkey(
                "ctrl",
                "z"
            )


        elif key == "redo":

            pyautogui.hotkey(
                "ctrl",
                "y"
            )


        elif key == "select_all":

            pyautogui.hotkey(
                "ctrl",
                "a"
            )


        elif key == "alt_tab":

            pyautogui.hotkey(
                "alt",
                "tab"
            )


        elif key == "alt_f4":

            pyautogui.hotkey(
                "alt",
                "f4"
            )


        elif key == "task_manager":

            pyautogui.hotkey(
                "ctrl",
                "shift",
                "esc"
            )


        elif key == "win_lock":

            pyautogui.hotkey(
                "win",
                "l"
            )


        elif key == "win_run":

            pyautogui.hotkey(
                "win",
                "r"
            )


        elif key == "save":

            pyautogui.hotkey(
                "ctrl",
                "s"
            )


    # ============================================================
    # SHORTCUT
    # ============================================================

    def shortcut(
            self,
            modifier_id: int,
            key_id: int
    ):

        modifier = MODIFIER_NAMES.get(modifier_id)

        if modifier is None:
            return

        key = KEY_ID_NAMES[key_id]

        mod_vk = VK.get(modifier)
        key_vk = VK.get(key)

        if mod_vk is None or key_vk is None:
            print("[KEYBOARD] Unsupported shortcut")
            return

        print(
            f"[KEYBOARD] SHORTCUT -> "
            f"{modifier} + {key}"
        )

        # Same SendInput path as held modifiers.
        # Exact order:
        # MODIFIER DOWN -> KEY DOWN -> KEY UP -> MODIFIER UP.
        try:
            self._key_down_vk(mod_vk)
            try:
                self._key_down_vk(key_vk)
            finally:
                self._key_up_vk(key_vk)
        finally:
            self._key_up_vk(mod_vk)


    # ============================================================
    # LANGUAGE
    # ============================================================


    def set_language(

        self,

        language: int
    ):


        layout_name = (

            LANGUAGE_LAYOUTS.get(
                language
            )
        )


        if layout_name is None:


            print(

                "[KEYBOARD] Unknown language:",

                language
            )


            return False


        print(

            f"[KEYBOARD] SET LANGUAGE -> "

            f"{language}"
        )


        try:


            layout = (

                self.user32.LoadKeyboardLayoutW(

                    layout_name,

                    1
                )
            )


            if not layout:


                print(

                    "[KEYBOARD] "

                    "LoadKeyboardLayoutW failed"
                )


                return False


            self.user32.PostMessageW(

                HWND_BROADCAST,

                WM_INPUTLANGCHANGEREQUEST,

                0,

                layout
            )


            return True


        except Exception as e:


            print(

                "[KEYBOARD] Language error:",

                e
            )


            return False