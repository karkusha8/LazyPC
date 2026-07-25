package com.example.lazypc.input.events

sealed class GestureEvent {
    object Tap : GestureEvent()
    object DoubleTap : GestureEvent()

    object ContextMenu : GestureEvent()

    object DragStart : GestureEvent()
    data class DragMove(val dx: Float, val dy: Float) : GestureEvent()
    object DragEnd : GestureEvent()

    data class Move(val dx: Float, val dy: Float) : GestureEvent()

    data class Scroll(val dy: Float) : GestureEvent()
}
