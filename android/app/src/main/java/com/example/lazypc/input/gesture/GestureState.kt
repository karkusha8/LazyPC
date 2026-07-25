package com.example.lazypc.input.gesture

internal class GestureState {

    var downTime = 0L
    var lastTapTime = 0L

    var startX = 0f
    var startY = 0f
    var lastX = 0f
    var lastY = 0f

    var moved = false
    var scrollActive = false

    var dragActive = false
    var longPressTriggered = false

    fun resetTap() {
        moved = false
        longPressTriggered = false
    }
    fun resetPosition(x: Float, y: Float) {
        startX = x
        startY = y
        lastX = x
        lastY = y
    }

}
