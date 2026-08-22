package com.example.lazypc.input.keyboard.core

enum class KeyId {
    // -------- LETTERS --------
    A, B, C, D, E, F, G,
    H, I, J, K, L, M,
    N, O, P, Q, R, S,
    T, U, V, W, X, Y, Z,

    // -------- SLAVIC EXTRA LETTER SLOTS --------
    // Used only by layouts which need more than 26 letters.
    // RU currently uses all seven slots:
    // Б, Ж, Х, Ъ, Э, Ю, Ё
    SLAVIC_1,
    SLAVIC_2,
    SLAVIC_3,
    SLAVIC_4,
    SLAVIC_5,
    SLAVIC_6,
    SLAVIC_7,

    // -------- DIGITS --------
    DIGIT_0, DIGIT_1, DIGIT_2, DIGIT_3, DIGIT_4,
    DIGIT_5, DIGIT_6, DIGIT_7, DIGIT_8, DIGIT_9,
    AT, HASH, DOLLAR, PERCENT,
    LBRACKET, RBRACKET,
    LCURLY, RCURLY,
    LPAREN, RPAREN,
    EQUALS, LESS, GREATER,
    UNDERSCORE,
    COLON, SEMICOLON,
    MINUS, PLUS,
    BACKSLASH, PIPE, QUESTION,
    DOT, COMMA, SLASH,

    // -------- BASIC KEYS --------
    SPACE,
    ENTER,
    BACKSPACE,
    TAB,
    SHIFT,
    ESC,

    CTRL,
    ALT,
    WIN,

    DEL,

    // -------- NAVIGATION --------
    LEFT,
    RIGHT,
    UP,
    DOWN,

    HOME,
    END,

    // -------- FUNCTION KEYS --------
    F5,
    F9,
    F10,
    F11,

    // -------- COMMANDS --------
    COPY,
    PASTE,
    CUT,
    UNDO,
    REDO,
    SELECT_ALL,

    // -------- SYSTEM COMMANDS --------
    ALT_TAB,
    ALT_F4,
    CTRL_ALT_DEL,
    TASK_MANAGER,
    WIN_LOCK,
    WIN_RUN,

    // -------- LAYER CONTROL --------
    SWITCH_TEXT,
    SWITCH_SYMBOLS,
    SWITCH_DEV,
    SAVE,
    SWITCH_CODE,
    F4,
    SWITCH_SYS,
    QUOTE,
}
