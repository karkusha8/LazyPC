package com.example.lazypc.input.keyboard.layout

import com.example.lazypc.input.keyboard.core.KeyId

object KeyboardLayouts {

    // =========================
    // ENGLISH / LATIN TEXT
    // =========================
    // DO NOT change this geometry for English.
    val MAIN_TEXT: KeyboardLayerLayout = listOf(
        listOf(
            KeyModel(KeyId.LBRACKET),
            KeyModel(KeyId.RBRACKET),
            KeyModel(KeyId.LCURLY),
            KeyModel(KeyId.RCURLY),
            KeyModel(KeyId.LPAREN),
            KeyModel(KeyId.RPAREN),
            KeyModel(KeyId.EQUALS),
            KeyModel(KeyId.DOT),
            KeyModel(KeyId.COMMA)
        ),

        listOf(
            KeyModel(KeyId.Q),
            KeyModel(KeyId.W),
            KeyModel(KeyId.E),
            KeyModel(KeyId.R),
            KeyModel(KeyId.T),
            KeyModel(KeyId.Y),
            KeyModel(KeyId.U),
            KeyModel(KeyId.I),
            KeyModel(KeyId.O),
            KeyModel(KeyId.P)
        ),

        listOf(
            KeyModel(KeyId.TAB, 1.5f),
            KeyModel(KeyId.A),
            KeyModel(KeyId.S),
            KeyModel(KeyId.D),
            KeyModel(KeyId.F),
            KeyModel(KeyId.G),
            KeyModel(KeyId.H),
            KeyModel(KeyId.J),
            KeyModel(KeyId.K),
            KeyModel(KeyId.L)
        ),

        listOf(
            KeyModel(KeyId.SHIFT, 1.5f),
            KeyModel(KeyId.Z),
            KeyModel(KeyId.X),
            KeyModel(KeyId.C),
            KeyModel(KeyId.V),
            KeyModel(KeyId.B),
            KeyModel(KeyId.N),
            KeyModel(KeyId.M),
            KeyModel(KeyId.BACKSPACE, 1.5f)
        ),

        listOf(
            KeyModel(KeyId.SWITCH_CODE),
            KeyModel(KeyId.SPACE, 4f),
            KeyModel(KeyId.ENTER, 1.5f)
        )
    )

    // =========================
    // SLAVIC TEXT
    // =========================
    // 33-letter geometry.
    //
    // RU:
    // Й Ц У К Е Н Г Ш Щ З Х Ъ
    // Ф Ы В А П Р О Л Д Ж Э
    // Я Ч С М И Т Ь Б Ю Ё
    //
    // The seven SLAVIC_* slots are intentionally generic so that
    // Ukrainian and other Cyrillic layouts can reuse this geometry later.
    val SLAVIC_TEXT: KeyboardLayerLayout = listOf(
        listOf(
            KeyModel(KeyId.LBRACKET),
            KeyModel(KeyId.RBRACKET),
            KeyModel(KeyId.LCURLY),
            KeyModel(KeyId.RCURLY),
            KeyModel(KeyId.LPAREN),
            KeyModel(KeyId.RPAREN),
            KeyModel(KeyId.EQUALS),
            KeyModel(KeyId.DOT),
            KeyModel(KeyId.COMMA)
        ),

        listOf(
            KeyModel(KeyId.Q),
            KeyModel(KeyId.W),
            KeyModel(KeyId.E),
            KeyModel(KeyId.R),
            KeyModel(KeyId.T),
            KeyModel(KeyId.Y),
            KeyModel(KeyId.U),
            KeyModel(KeyId.I),
            KeyModel(KeyId.O),
            KeyModel(KeyId.P),
            KeyModel(KeyId.SLAVIC_3), // Х
            KeyModel(KeyId.SLAVIC_4)  // Ъ
        ),

        listOf(
            KeyModel(KeyId.A),
            KeyModel(KeyId.S),
            KeyModel(KeyId.D),
            KeyModel(KeyId.F),
            KeyModel(KeyId.G),
            KeyModel(KeyId.H),
            KeyModel(KeyId.J),
            KeyModel(KeyId.K),
            KeyModel(KeyId.L),
            KeyModel(KeyId.SLAVIC_2), // Ж
            KeyModel(KeyId.SLAVIC_5)  // Э
        ),

        listOf(
            KeyModel(KeyId.SHIFT, 1.5f),
            KeyModel(KeyId.Z),
            KeyModel(KeyId.X),
            KeyModel(KeyId.C),
            KeyModel(KeyId.V),
            KeyModel(KeyId.B),
            KeyModel(KeyId.N),
            KeyModel(KeyId.M),
            KeyModel(KeyId.SLAVIC_1), // Б
            KeyModel(KeyId.SLAVIC_6), // Ю
            KeyModel(KeyId.BACKSPACE, 1.5f)
        ),

        listOf(
            KeyModel(KeyId.SWITCH_CODE),
            KeyModel(KeyId.SPACE, 4f),
            KeyModel(KeyId.ENTER, 1.5f),

        )
    )

    // =========================
    // MAIN SYMBOLS
    // =========================
    val MAIN_SYMBOLS: KeyboardLayerLayout = listOf(
        listOf(
            KeyModel(KeyId.DIGIT_1),
            KeyModel(KeyId.DIGIT_2),
            KeyModel(KeyId.DIGIT_3),
            KeyModel(KeyId.DIGIT_4),
            KeyModel(KeyId.DIGIT_5),
            KeyModel(KeyId.DIGIT_6),
            KeyModel(KeyId.DIGIT_7),
            KeyModel(KeyId.DIGIT_8),
            KeyModel(KeyId.DIGIT_9),
            KeyModel(KeyId.DIGIT_0)
        ),

        listOf(
            KeyModel(KeyId.TAB, 1.5f),
            KeyModel(KeyId.AT),
            KeyModel(KeyId.HASH),
            KeyModel(KeyId.DOLLAR),
            KeyModel(KeyId.PERCENT),
            KeyModel(KeyId.LBRACKET),
            KeyModel(KeyId.RBRACKET),
            KeyModel(KeyId.LCURLY),
            KeyModel(KeyId.RCURLY)
        ),

        listOf(
            KeyModel(KeyId.EQUALS),
            KeyModel(KeyId.LESS),
            KeyModel(KeyId.GREATER),
            KeyModel(KeyId.UNDERSCORE),
            KeyModel(KeyId.LPAREN),
            KeyModel(KeyId.RPAREN),
            KeyModel(KeyId.COLON),
            KeyModel(KeyId.SEMICOLON)
        ),

        listOf(
            KeyModel(KeyId.MINUS),
            KeyModel(KeyId.PLUS),
            KeyModel(KeyId.BACKSLASH),
            KeyModel(KeyId.PIPE),
            KeyModel(KeyId.QUESTION),
            KeyModel(KeyId.DOT),
            KeyModel(KeyId.COMMA),
            KeyModel(KeyId.SLASH),
            KeyModel(KeyId.BACKSPACE, 1.5f)
        ),

        listOf(
            KeyModel(KeyId.SWITCH_TEXT, 1.5f),
            KeyModel(KeyId.SPACE, 4f),
            KeyModel(KeyId.ENTER, 1.5f)
        )
    )

    // =========================
    // DEV
    // =========================
    val DEV: KeyboardLayerLayout = listOf(
        listOf(
            KeyModel(KeyId.ESC),
            KeyModel(KeyId.F4),
            KeyModel(KeyId.F5),
            KeyModel(KeyId.F9),
            KeyModel(KeyId.F10),
            KeyModel(KeyId.F11)
        ),

        listOf(
            KeyModel(KeyId.TAB),
            KeyModel(KeyId.CUT),
            KeyModel(KeyId.COPY),
            KeyModel(KeyId.PASTE),
            KeyModel(KeyId.SAVE)
        ),

        listOf(
            KeyModel(KeyId.HOME),
            KeyModel(KeyId.UP),
            KeyModel(KeyId.END)
        ),

        listOf(
            KeyModel(KeyId.LEFT),
            KeyModel(KeyId.DOWN),
            KeyModel(KeyId.RIGHT)
        ),

        listOf(
            KeyModel(KeyId.CTRL, 1.5f),
            KeyModel(KeyId.ALT, 1.5f),
            KeyModel(KeyId.SPACE, 3f),
            KeyModel(KeyId.ENTER, 1.5f),
            KeyModel(KeyId.BACKSPACE, 1.5f)
        )
    )
}
