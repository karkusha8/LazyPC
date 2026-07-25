package com.example.lazypc.keyboard.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.lazypc.keyboard.core.*
import com.example.lazypc.keyboard.emit.KeyboardEmitter
import com.example.lazypc.keyboard.layout.KeyboardLayouts
import com.example.lazypc.keyboard.mapping.LanguageEN
import com.example.lazypc.keyboard.mapping.LanguageRU


@Composable
fun KeyboardScreen(

    keyboardEngine: KeyboardEngine,

    keyboardEmitter: KeyboardEmitter,

    modifier: Modifier = Modifier

) {

    val shift by
    keyboardEngine
        .shiftEnabled
        .collectAsStateWithLifecycle()


    val caps by
    keyboardEngine
        .capsLockEnabled
        .collectAsStateWithLifecycle()


    val layer by
    keyboardEngine
        .currentLayer
        .collectAsStateWithLifecycle()


    val language by
    keyboardEngine
        .currentLanguage
        .collectAsStateWithLifecycle()


    val layout =

        when (layer) {

            KeyboardLayer.TEXT ->
                KeyboardLayouts.MAIN_TEXT

            KeyboardLayer.CODE ->
                KeyboardLayouts.MAIN_SYMBOLS

            KeyboardLayer.SYS ->
                KeyboardLayouts.DEV
        }


    Column(

        modifier = modifier

            .fillMaxWidth()

            .background(
                Color(0xFF1E1E1E)
            )

    ) {


        Row(

            modifier = Modifier

                .fillMaxWidth()

                .height(48.dp)

                .padding(
                    horizontal = 8.dp
                ),

            verticalAlignment =
                Alignment.CenterVertically

        ) {


            TabItem(

                title = "ABC",

                active =
                    layer != KeyboardLayer.SYS

            ) {

                keyboardEngine.setLayer(
                    KeyboardLayer.TEXT
                )
            }


            TabItem(

                title = "DEV",

                active =
                    layer == KeyboardLayer.SYS

            ) {

                keyboardEngine.setLayer(
                    KeyboardLayer.SYS
                )
            }


            LanguageItem(

                title =

                    when (language) {

                        is LanguageRU ->
                            "RU"

                        is LanguageEN ->
                            "EN"

                        else ->
                            "EN"
                    }

            ) {

                keyboardEngine
                    .switchLanguage()
            }
        }


        Spacer(

            modifier =
                Modifier.height(4.dp)
        )


        Column(

            modifier = Modifier

                .fillMaxSize()

                .padding(4.dp)

        ) {


            layout.forEach { row ->


                Row(

                    modifier = Modifier

                        .fillMaxWidth()

                        .weight(1f)

                ) {


                    row.forEach { key ->


                        val baseLabel =

                            labelForKey(

                                key.id,

                                language
                            )


                        val displayLabel =

                            when {

                                baseLabel.length == 1 &&
                                        baseLabel[0].isLetter() -> {

                                    if (shift || caps)

                                        baseLabel.uppercase()

                                    else

                                        baseLabel.lowercase()
                                }


                                else ->
                                    baseLabel
                            }


                        val isShiftKey =

                            key.id ==
                                    KeyId.SHIFT


                        val bgColor =

                            when {

                                isShiftKey && caps ->

                                    Color(0xFF4CAF50)


                                isShiftKey && shift ->

                                    Color(0xFF2196F3)


                                else ->

                                    Color(0xFF2A2A2A)
                            }


                        KeyButton(

                            keyId =
                                key.id,

                            label =
                                displayLabel,

                            weight =
                                key.width,

                            backgroundColor =
                                bgColor

                        ) { pressedKey ->


                            val action =

                                keyboardEngine
                                    .handleKey(
                                        pressedKey
                                    )


                            action?.let {

                                keyboardEmitter
                                    .emit(it)
                            }
                        }
                    }
                }
            }
        }
    }
}


@Composable
fun RowScope.KeyButton(

    keyId: KeyId,

    label: String,

    weight: Float,

    backgroundColor: Color =
        Color(0xFF2A2A2A),

    onClick: (KeyId) -> Unit

) {

    Box(

        modifier = Modifier

            .weight(weight)

            .fillMaxHeight()

            .padding(2.dp)

            .background(

                backgroundColor,

                RoundedCornerShape(8.dp)
            )

            .clickable {

                onClick(keyId)
            },

        contentAlignment =
            Alignment.Center

    ) {

        Text(

            text =
                label,

            color =
                Color.White,

            fontSize =
                16.sp,

            fontWeight =
                FontWeight.Medium
        )
    }
}


fun labelForKey(

    key: KeyId,

    language: Any

): String {


    val letterLabel =

        when (language) {


            is LanguageRU ->

                when (key) {

                    KeyId.Q -> "й"
                    KeyId.W -> "ц"
                    KeyId.E -> "у"
                    KeyId.R -> "к"
                    KeyId.T -> "е"
                    KeyId.Y -> "н"
                    KeyId.U -> "г"
                    KeyId.I -> "ш"
                    KeyId.O -> "щ"
                    KeyId.P -> "з"

                    KeyId.A -> "ф"
                    KeyId.S -> "ы"
                    KeyId.D -> "в"
                    KeyId.F -> "а"
                    KeyId.G -> "п"
                    KeyId.H -> "р"
                    KeyId.J -> "о"
                    KeyId.K -> "л"
                    KeyId.L -> "д"

                    KeyId.Z -> "я"
                    KeyId.X -> "ч"
                    KeyId.C -> "с"
                    KeyId.V -> "м"
                    KeyId.B -> "и"
                    KeyId.N -> "т"
                    KeyId.M -> "ь"

                    else ->
                        null
                }


            else ->

                when (key) {

                    KeyId.Q -> "q"
                    KeyId.W -> "w"
                    KeyId.E -> "e"
                    KeyId.R -> "r"
                    KeyId.T -> "t"
                    KeyId.Y -> "y"
                    KeyId.U -> "u"
                    KeyId.I -> "i"
                    KeyId.O -> "o"
                    KeyId.P -> "p"

                    KeyId.A -> "a"
                    KeyId.S -> "s"
                    KeyId.D -> "d"
                    KeyId.F -> "f"
                    KeyId.G -> "g"
                    KeyId.H -> "h"
                    KeyId.J -> "j"
                    KeyId.K -> "k"
                    KeyId.L -> "l"

                    KeyId.Z -> "z"
                    KeyId.X -> "x"
                    KeyId.C -> "c"
                    KeyId.V -> "v"
                    KeyId.B -> "b"
                    KeyId.N -> "n"
                    KeyId.M -> "m"

                    else ->
                        null
                }
        }


    if (letterLabel != null) {

        return letterLabel
    }


    return when (key) {

        KeyId.DIGIT_0 -> "0"
        KeyId.DIGIT_1 -> "1"
        KeyId.DIGIT_2 -> "2"
        KeyId.DIGIT_3 -> "3"
        KeyId.DIGIT_4 -> "4"
        KeyId.DIGIT_5 -> "5"
        KeyId.DIGIT_6 -> "6"
        KeyId.DIGIT_7 -> "7"
        KeyId.DIGIT_8 -> "8"
        KeyId.DIGIT_9 -> "9"

        KeyId.AT -> "@"
        KeyId.HASH -> "#"
        KeyId.DOLLAR -> "$"
        KeyId.PERCENT -> "%"

        KeyId.LPAREN -> "("
        KeyId.RPAREN -> ")"

        KeyId.LBRACKET -> "["
        KeyId.RBRACKET -> "]"

        KeyId.LCURLY -> "{"
        KeyId.RCURLY -> "}"

        KeyId.PLUS -> "+"
        KeyId.MINUS -> "-"
        KeyId.EQUALS -> "="

        KeyId.LESS -> "<"
        KeyId.GREATER -> ">"

        KeyId.UNDERSCORE -> "_"

        KeyId.COLON -> ":"
        KeyId.SEMICOLON -> ";"

        KeyId.DOT -> "."
        KeyId.COMMA -> ","

        KeyId.SLASH -> "/"
        KeyId.BACKSLASH -> "\\"

        KeyId.PIPE -> "|"

        KeyId.QUESTION -> "?"

        KeyId.ENTER -> "⏎"

        KeyId.BACKSPACE -> "⌫"

        KeyId.SHIFT -> "⇧"

        KeyId.TAB -> "TAB"

        KeyId.SPACE -> "SPACE"

        KeyId.SWITCH_TEXT -> "ABC"

        KeyId.SWITCH_CODE -> "123"

        KeyId.SWITCH_SYS -> "DEV"

        KeyId.LEFT -> "←"
        KeyId.RIGHT -> "→"
        KeyId.UP -> "↑"
        KeyId.DOWN -> "↓"

        else ->
            key.name
    }
}


@Composable
private fun RowScope.TabItem(

    title: String,

    active: Boolean,

    onClick: () -> Unit

) {

    Column(

        modifier = Modifier

            .weight(1f)

            .fillMaxHeight()

            .clickable {

                onClick()
            },

        horizontalAlignment =
            Alignment.CenterHorizontally,

        verticalArrangement =
            Arrangement.Center

    ) {

        Text(

            text =
                title,

            color =

                if (active)

                    Color.White

                else

                    Color.Gray,

            fontWeight =

                if (active)

                    FontWeight.SemiBold

                else

                    FontWeight.Normal
        )


        Spacer(

            modifier =
                Modifier.height(6.dp)
        )


        Box(

            modifier = Modifier

                .height(2.dp)

                .fillMaxWidth(0.5f)

                .background(

                    if (active)

                        Color.White

                    else

                        Color.Transparent,

                    RoundedCornerShape(1.dp)
                )
        )
    }
}


@Composable
private fun RowScope.LanguageItem(

    title: String,

    onClick: () -> Unit

) {

    Box(

        modifier = Modifier

            .weight(0.55f)

            .fillMaxHeight()

            .padding(

                horizontal = 4.dp,

                vertical = 5.dp
            )

            .background(

                Color(0xFF2A2A2A),

                RoundedCornerShape(8.dp)
            )

            .clickable {

                onClick()
            },

        contentAlignment =
            Alignment.Center

    ) {

        Text(

            text =
                "🌐 $title",

            color =
                Color.White,

            fontWeight =
                FontWeight.SemiBold
        )
    }
}