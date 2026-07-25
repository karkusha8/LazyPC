package com.example.lazypc.keyboard.mapping

import com.example.lazypc.keyboard.core.KeyId


class LanguageEN : Language {

    override fun map(
        keyId: KeyId,
        shift: Boolean
    ): String? {

        return when (keyId) {

            // ========================================================
            // LETTERS
            // ========================================================

            KeyId.A -> if (shift) "A" else "a"
            KeyId.B -> if (shift) "B" else "b"
            KeyId.C -> if (shift) "C" else "c"
            KeyId.D -> if (shift) "D" else "d"
            KeyId.E -> if (shift) "E" else "e"
            KeyId.F -> if (shift) "F" else "f"
            KeyId.G -> if (shift) "G" else "g"
            KeyId.H -> if (shift) "H" else "h"
            KeyId.I -> if (shift) "I" else "i"
            KeyId.J -> if (shift) "J" else "j"
            KeyId.K -> if (shift) "K" else "k"
            KeyId.L -> if (shift) "L" else "l"
            KeyId.M -> if (shift) "M" else "m"
            KeyId.N -> if (shift) "N" else "n"
            KeyId.O -> if (shift) "O" else "o"
            KeyId.P -> if (shift) "P" else "p"
            KeyId.Q -> if (shift) "Q" else "q"
            KeyId.R -> if (shift) "R" else "r"
            KeyId.S -> if (shift) "S" else "s"
            KeyId.T -> if (shift) "T" else "t"
            KeyId.U -> if (shift) "U" else "u"
            KeyId.V -> if (shift) "V" else "v"
            KeyId.W -> if (shift) "W" else "w"
            KeyId.X -> if (shift) "X" else "x"
            KeyId.Y -> if (shift) "Y" else "y"
            KeyId.Z -> if (shift) "Z" else "z"


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

            KeyId.LBRACKET ->
                if (shift) "{" else "["

            KeyId.RBRACKET ->
                if (shift) "}" else "]"


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

            KeyId.EQUALS ->
                if (shift) "+" else "="

            KeyId.MINUS ->
                if (shift) "_" else "-"


            KeyId.PLUS -> "+"

            KeyId.UNDERSCORE -> "_"


            // ========================================================
            // PUNCTUATION
            // ========================================================

            KeyId.DOT ->
                if (shift) ">" else "."

            KeyId.COMMA ->
                if (shift) "<" else ","


            KeyId.COLON -> ":"

            KeyId.SEMICOLON ->
                if (shift) ":" else ";"


            KeyId.QUOTE ->
                if (shift) "\"" else "'"


            KeyId.QUESTION -> "?"


            // ========================================================
            // SLASHES
            // ========================================================

            KeyId.SLASH ->
                if (shift) "?" else "/"

            KeyId.BACKSLASH ->
                if (shift) "|" else "\\"


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