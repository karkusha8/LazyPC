package com.example.lazypc.input

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.setValue


class CursorState {

    var x by mutableFloatStateOf(0f)
        private set

    var y by mutableFloatStateOf(0f)
        private set


    private var initialized = false


    fun initialize(
        width: Float,
        height: Float
    ) {

        if (initialized) {
            return
        }

        if (width <= 0f || height <= 0f) {
            return
        }

        x = width / 2f
        y = height / 2f

        initialized = true
    }


    fun move(
        dx: Float,
        dy: Float,
        width: Float,
        height: Float
    ) {

        initialize(
            width,
            height
        )

        if (width <= 0f || height <= 0f) {
            return
        }

        x = (x + dx).coerceIn(
            0f,
            width
        )

        y = (y + dy).coerceIn(
            0f,
            height
        )
    }


    /*
     * ================================================================
     * WINDOWS CURSOR SYNCHRONIZATION
     * ================================================================
     */


    fun setNormalizedPosition(
        normalizedX: Float,
        normalizedY: Float,
        width: Float,
        height: Float
    ) {

        if (width <= 0f || height <= 0f) {
            return
        }

        val safeX =
            normalizedX.coerceIn(
                0f,
                1f
            )

        val safeY =
            normalizedY.coerceIn(
                0f,
                1f
            )

        x = safeX * width
        y = safeY * height

        initialized = true
    }


    fun reset() {

        initialized = false

        x = 0f
        y = 0f
    }
}