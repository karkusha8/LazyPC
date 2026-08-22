package com.example.lazypc.input.keyboard.mapping

import com.example.lazypc.input.keyboard.core.KeyId

class LanguageRU : Language {

    override fun map(
        keyId: KeyId,
        shift: Boolean
    ): String? {

        return when (keyId) {

            // ========================================================
            // RUSSIAN / SLAVIC LETTERS
            // ========================================================

            KeyId.Q -> if (shift) "Й" else "й"
            KeyId.W -> if (shift) "Ц" else "ц"
            KeyId.E -> if (shift) "У" else "у"
            KeyId.R -> if (shift) "К" else "к"
            KeyId.T -> if (shift) "Е" else "е"
            KeyId.Y -> if (shift) "Н" else "н"
            KeyId.U -> if (shift) "Г" else "г"
            KeyId.I -> if (shift) "Ш" else "ш"
            KeyId.O -> if (shift) "Щ" else "щ"
            KeyId.P -> if (shift) "З" else "з"

            KeyId.A -> if (shift) "Ф" else "ф"
            KeyId.S -> if (shift) "Ы" else "ы"
            KeyId.D -> if (shift) "В" else "в"
            KeyId.F -> if (shift) "А" else "а"
            KeyId.G -> if (shift) "П" else "п"
            KeyId.H -> if (shift) "Р" else "р"
            KeyId.J -> if (shift) "О" else "о"
            KeyId.K -> if (shift) "Л" else "л"
            KeyId.L -> if (shift) "Д" else "д"

            KeyId.Z -> if (shift) "Я" else "я"
            KeyId.X -> if (shift) "Ч" else "ч"
            KeyId.C -> if (shift) "С" else "с"
            KeyId.V -> if (shift) "М" else "м"
            KeyId.B -> if (shift) "И" else "и"
            KeyId.N -> if (shift) "Т" else "т"
            KeyId.M -> if (shift) "Ь" else "ь"

            // Additional Cyrillic slots.
            // These are shared by Slavic layouts such as RU/UK.
            KeyId.SLAVIC_1 -> if (shift) "Б" else "б"
            KeyId.SLAVIC_2 -> if (shift) "Ж" else "ж"
            KeyId.SLAVIC_3 -> if (shift) "Х" else "х"
            KeyId.SLAVIC_4 -> if (shift) "Ъ" else "ъ"
            KeyId.SLAVIC_5 -> if (shift) "Э" else "э"
            KeyId.SLAVIC_6 -> if (shift) "Ю" else "ю"
            KeyId.SLAVIC_7 -> if (shift) "Ё" else "ё"

            // ========================================================
            // DIGITS
            // ========================================================

            KeyId.DIGIT_0 -> if (shift) ")" else "0"
            KeyId.DIGIT_1 -> if (shift) "!" else "1"
            KeyId.DIGIT_2 -> if (shift) "@" else "2"
            KeyId.DIGIT_3 -> if (shift) "#" else "3"
            KeyId.DIGIT_4 -> if (shift) "$" else "4"
            KeyId.DIGIT_5 -> if (shift) "%" else "5"
            KeyId.DIGIT_6 -> if (shift) "^" else "6"
            KeyId.DIGIT_7 -> if (shift) "&" else "7"
            KeyId.DIGIT_8 -> if (shift) "*" else "8"
            KeyId.DIGIT_9 -> if (shift) "(" else "9"

            // ========================================================
            // DIRECT SYMBOLS
            // ========================================================

            KeyId.AT -> "@"
            KeyId.HASH -> "#"
            KeyId.DOLLAR -> "$"
            KeyId.PERCENT -> "%"

            // ========================================================
            // BRACKETS
            // ========================================================

            KeyId.LBRACKET -> if (shift) "{" else "["
            KeyId.RBRACKET -> if (shift) "}" else "]"

            KeyId.LCURLY -> "{"
            KeyId.RCURLY -> "}"

            KeyId.LPAREN -> "("
            KeyId.RPAREN -> ")"

            // ========================================================
            // COMPARISON
            // ========================================================

            KeyId.LESS -> "<"
            KeyId.GREATER -> ">"

            // ========================================================
            // OPERATORS
            // ========================================================

            KeyId.EQUALS -> if (shift) "+" else "="
            KeyId.MINUS -> if (shift) "_" else "-"

            KeyId.PLUS -> "+"
            KeyId.UNDERSCORE -> "_"

            // ========================================================
            // PUNCTUATION
            // ========================================================

            KeyId.DOT -> if (shift) ">" else "."
            KeyId.COMMA -> if (shift) "<" else ","

            KeyId.COLON -> ":"
            KeyId.SEMICOLON -> if (shift) ":" else ";"

            KeyId.QUOTE -> if (shift) "\"" else "'"

            KeyId.QUESTION -> "?"

            // ========================================================
            // SLASHES
            // ========================================================

            KeyId.SLASH -> if (shift) "?" else "/"

            KeyId.BACKSLASH -> if (shift) "|" else "\\"

            KeyId.PIPE -> "|"

            // ========================================================
            // SPACE
            // ========================================================

            KeyId.SPACE -> " "

            // ========================================================
            // UNKNOWN / NON-PRINTABLE
            // ========================================================

            else -> null
        }
    }
}