package com.example.lazypc.keyboard.layout

import com.example.lazypc.keyboard.core.KeyId

data class KeyRow(
    val keys: List<KeyId>
)

class MobileLayout {

    val rows: List<KeyRow> = listOf(

        // QWERTY
        KeyRow(listOf(
            KeyId.Q, KeyId.W, KeyId.E, KeyId.R, KeyId.T,
            KeyId.Y, KeyId.U, KeyId.I, KeyId.O, KeyId.P
        )),

        // ASDF
        KeyRow(listOf(
            KeyId.A, KeyId.S, KeyId.D, KeyId.F, KeyId.G,
            KeyId.H, KeyId.J, KeyId.K, KeyId.L
        )),

        // SHIFT + ZXCV + BACKSPACE
        KeyRow(listOf(
            KeyId.SHIFT,
            KeyId.Z, KeyId.X, KeyId.C, KeyId.V,
            KeyId.B, KeyId.N, KeyId.M,
            KeyId.BACKSPACE
        )),

        // CONTROL ROW
        KeyRow(listOf(
            KeyId.SWITCH_CODE,
            KeyId.TAB,
            KeyId.SPACE,
            KeyId.ENTER
        ))
    )
}