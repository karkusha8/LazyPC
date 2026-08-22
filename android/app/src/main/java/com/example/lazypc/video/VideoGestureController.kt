package com.example.lazypc.video

import android.view.MotionEvent

/**
 * Connects touch intent recognition with the video viewport.
 *
 * TouchGestureInterpreter decides WHAT the user wants.
 * VideoGestureController decides HOW that intention changes the viewport.
 */
class VideoGestureController(
    private val viewport: ScreenViewport,
    onMouseEvent: (MotionEvent) -> Unit,
    private val onPanModeChanged: (Boolean) -> Unit,
    private val onRecenterMouse: (Float, Float) -> Unit
) {
    private val interpreter =
        TouchGestureInterpreter(
            onMouseEvent = onMouseEvent,
            onAction = ::handleAction
        )

    fun handleTouch(event: MotionEvent) {
        interpreter.handle(event)
    }

    fun updateTouchAreaSize(
        width: Float,
        height: Float
    ) {
        interpreter.updateTouchAreaSize(
            width = width,
            height = height
        )
    }

    fun exitPanMode() {
        interpreter.exitPanMode()
    }

    fun dispose() {
        interpreter.dispose()
    }

    private fun handleAction(
        action: TouchGestureInterpreter.Action
    ) {
        when (action) {
            is TouchGestureInterpreter.Action.Zoom -> {
                viewport.zoomAt(
                    factor = action.factor,
                    focusX = action.focusX,
                    focusY = action.focusY
                )
            }

            is TouchGestureInterpreter.Action.Pan -> {
                viewport.panBy(
                    dx = action.dx,
                    dy = action.dy
                )
            }

            is TouchGestureInterpreter.Action.ZoomEnd -> {
                /*
                 * ZoomEnd.focusX/focusY are final screen coordinates of the
                 * pinch focus. CursorState uses the original fitted-video
                 * coordinate space, so convert the final visible point back
                 * through the CURRENT (final) zoom transform.
                 *
                 * This is intentionally done here because this class owns
                 * the viewport. MainActivity should not know about viewport.
                 */
                if (viewport.scale >= RECENTER_ZOOM_THRESHOLD) {
                    val scale = viewport.scale.coerceAtLeast(0.0001f)
                    val centerX = viewport.fittedWidth / 2f
                    val centerY = viewport.fittedHeight / 2f

                    val targetMouseX =
                        centerX +
                                (action.focusX - centerX - viewport.offsetX) / scale

                    val targetMouseY =
                        centerY +
                                (action.focusY - centerY - viewport.offsetY) / scale

                    onRecenterMouse(
                        targetMouseX,
                        targetMouseY
                    )
                }
            }

            TouchGestureInterpreter.Action.EnterPanMode -> {
                onPanModeChanged(true)
            }

            TouchGestureInterpreter.Action.ExitPanMode -> {
                onPanModeChanged(false)
            }
        }
    }

    companion object {
        private const val RECENTER_ZOOM_THRESHOLD = 2.0f
    }
}