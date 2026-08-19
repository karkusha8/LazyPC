package com.example.lazypc.input.keyboard.core

class ActionResolver {

    fun resolve(
        layer: KeyboardLayer,
        keyId: KeyId
    ): KeyAction? {

        return when (layer) {

            KeyboardLayer.TEXT ->
                textLayer(keyId)

            KeyboardLayer.CODE ->
                codeLayer(keyId)

            KeyboardLayer.SYS ->
                sysLayer(keyId)
        }
    }


    // ============================================================
    // TEXT LAYER
    // ============================================================

    private fun textLayer(
        keyId: KeyId
    ): KeyAction? {

        return when (keyId) {

            // ====================================================
            // LETTERS
            // ====================================================

            KeyId.A,
            KeyId.B,
            KeyId.C,
            KeyId.D,
            KeyId.E,
            KeyId.F,
            KeyId.G,
            KeyId.H,
            KeyId.I,
            KeyId.J,
            KeyId.K,
            KeyId.L,
            KeyId.M,
            KeyId.N,
            KeyId.O,
            KeyId.P,
            KeyId.Q,
            KeyId.R,
            KeyId.S,
            KeyId.T,
            KeyId.U,
            KeyId.V,
            KeyId.W,
            KeyId.X,
            KeyId.Y,
            KeyId.Z,

                // ====================================================
                // DIGITS
                // ====================================================

            KeyId.DIGIT_0,
            KeyId.DIGIT_1,
            KeyId.DIGIT_2,
            KeyId.DIGIT_3,
            KeyId.DIGIT_4,
            KeyId.DIGIT_5,
            KeyId.DIGIT_6,
            KeyId.DIGIT_7,
            KeyId.DIGIT_8,
            KeyId.DIGIT_9,

                // ====================================================
                // SYMBOLS
                // ====================================================

            KeyId.LPAREN,
            KeyId.RPAREN,

            KeyId.LBRACKET,
            KeyId.RBRACKET,

            KeyId.LCURLY,
            KeyId.RCURLY,

            KeyId.EQUALS,
            KeyId.MINUS,
            KeyId.PLUS,

            KeyId.SLASH,
            KeyId.BACKSLASH,

            KeyId.COLON,
            KeyId.SEMICOLON,

            KeyId.UNDERSCORE,

            KeyId.LESS,
            KeyId.GREATER,

            KeyId.QUESTION,

            KeyId.PIPE,

            KeyId.AT,
            KeyId.HASH,
            KeyId.DOLLAR,
            KeyId.PERCENT,

            KeyId.DOT,
            KeyId.COMMA,

            KeyId.SPACE ->

                KeyAction.Printable(keyId)


            // ====================================================
            // CONTROL KEYS
            // ====================================================

            KeyId.ENTER ->
                KeyAction.Key(KeyId.ENTER)

            KeyId.BACKSPACE ->
                KeyAction.Key(KeyId.BACKSPACE)

            KeyId.TAB ->
                KeyAction.Key(KeyId.TAB)

            KeyId.SHIFT ->
                KeyAction.Key(KeyId.SHIFT)


            else -> null
        }
    }


    // ============================================================
    // CODE LAYER
    // ============================================================

    private fun codeLayer(
        keyId: KeyId
    ): KeyAction? {

        return when (keyId) {

            KeyId.COPY ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.C
                )

            KeyId.PASTE ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.V
                )

            KeyId.CUT ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.X
                )

            KeyId.SAVE ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.S
                )


            else ->
                textLayer(keyId)
        }
    }


    // ============================================================
    // SYS / DEV LAYER
    // ============================================================

    private fun sysLayer(
        keyId: KeyId
    ): KeyAction? {

        return when (keyId) {

            // ====================================================
            // SHORTCUTS
            // ====================================================

            KeyId.COPY ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.C
                )

            KeyId.PASTE ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.V
                )

            KeyId.CUT ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.X
                )

            KeyId.SAVE ->
                KeyAction.Shortcut(
                    KeyId.CTRL,
                    KeyId.S
                )


            // ====================================================
            // SYSTEM SHORTCUTS
            // ====================================================

            KeyId.ALT_TAB ->
                KeyAction.Shortcut(
                    KeyId.ALT,
                    KeyId.TAB
                )


            // ====================================================
            // NAVIGATION
            // ====================================================

            KeyId.LEFT ->
                KeyAction.Key(KeyId.LEFT)

            KeyId.RIGHT ->
                KeyAction.Key(KeyId.RIGHT)

            KeyId.UP ->
                KeyAction.Key(KeyId.UP)

            KeyId.DOWN ->
                KeyAction.Key(KeyId.DOWN)

            KeyId.HOME ->
                KeyAction.Key(KeyId.HOME)

            KeyId.END ->
                KeyAction.Key(KeyId.END)


            // ====================================================
            // CONTROL KEYS
            // ====================================================

            KeyId.ESC ->
                KeyAction.Key(KeyId.ESC)

            KeyId.TAB ->
                KeyAction.Key(KeyId.TAB)

            KeyId.ENTER ->
                KeyAction.Key(KeyId.ENTER)

            KeyId.CTRL ->
                KeyAction.Key(KeyId.CTRL)


            // ====================================================
            // SPACE
            // ====================================================

            KeyId.SPACE ->
                KeyAction.Printable(KeyId.SPACE)


            // ====================================================
            // FUNCTION KEYS
            // ====================================================

            KeyId.F5 ->
                KeyAction.Key(KeyId.F5)

            KeyId.F9 ->
                KeyAction.Key(KeyId.F9)

            KeyId.F10 ->
                KeyAction.Key(KeyId.F10)

            KeyId.F11 ->
                KeyAction.Key(KeyId.F11)


            else -> null
        }
    }
}