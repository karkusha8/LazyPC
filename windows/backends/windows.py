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

    66: "ctrl",

    67: "alt",

    64: "shift",
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


        modifier = (

            MODIFIER_NAMES.get(
                modifier_id
            )
        )


        if modifier is None:


            print(

                "[KEYBOARD] Unknown modifier:",

                modifier_id
            )


            return


        if (

            key_id < 0

            or

            key_id >= len(KEY_ID_NAMES)

        ):


            print(

                "[KEYBOARD] Unknown shortcut KeyId:",

                key_id
            )


            return


        key = (

            KEY_ID_NAMES[
                key_id
            ]
        )


        print(

            f"[KEYBOARD] SHORTCUT -> "

            f"{modifier} + {key}"
        )


        try:


            pyautogui.keyDown(
                modifier
            )


            pyautogui.press(
                key
            )


        finally:


            pyautogui.keyUp(
                modifier
            )


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