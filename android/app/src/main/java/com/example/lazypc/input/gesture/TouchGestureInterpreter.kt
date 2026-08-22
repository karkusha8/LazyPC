package com.example.lazypc.video

import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import kotlin.math.abs
import kotlin.math.hypot

/**
 * Converts raw Android touch events into high-level intentions.
 *
 * This class deliberately knows nothing about Compose or ScreenViewport.
 * It only decides what the user is trying to do.
 */
class TouchGestureInterpreter(
    private val onMouseEvent: (MotionEvent) -> Unit,
    private val onAction: (Action) -> Unit
) {
    sealed interface Action {
        data class Zoom(
            val factor: Float,
            val focusX: Float,
            val focusY: Float
        ) : Action

        data class ZoomEnd(
            val focusX: Float,
            val focusY: Float
        ) : Action

        data class Pan(
            val dx: Float,
            val dy: Float
        ) : Action

        data object EnterPanMode : Action
        data object ExitPanMode : Action
    }

    private enum class TwoFingerIntent {
        UNDECIDED,
        SCROLL,
        PINCH
    }

    private var panModeActive = false
    private var twoFingerHoldActive = false
    private var twoFingerIntent = TwoFingerIntent.UNDECIDED
    private var scrollForwarding = false

    private var holdStartX = 0f
    private var holdStartY = 0f

    private var lastPanX = 0f
    private var lastPanY = 0f

    private var lastSpan = 0f

    private var lastPinchFocusX = 0f
    private var lastPinchFocusY = 0f

    private var panExitPressed = false
    private var touchAreaWidth = 0f
    private var touchAreaHeight = 0f

    private val handler = Handler(Looper.getMainLooper())

    private val enterPanModeRunnable = Runnable {
        if (!twoFingerHoldActive) return@Runnable
        if (twoFingerIntent != TwoFingerIntent.UNDECIDED) return@Runnable

        panModeActive = true
        twoFingerHoldActive = false
        twoFingerIntent = TwoFingerIntent.UNDECIDED
        lastSpan = 0f

        onAction(Action.EnterPanMode)
    }

    private val exitPanModeRunnable = Runnable {
        if (!panModeActive) return@Runnable
        if (!twoFingerHoldActive) return@Runnable
        if (twoFingerIntent != TwoFingerIntent.UNDECIDED) return@Runnable

        // Use the same full state transition as the close button.
        // Previously we only emitted ExitPanMode, which hid the overlay
        // but left the interpreter internally in PAN MODE.
        exitPanMode()
    }

    fun updateTouchAreaSize(
        width: Float,
        height: Float
    ) {
        touchAreaWidth = width
        touchAreaHeight = height
    }

    fun handle(event: MotionEvent) {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> handleDown(event)
            MotionEvent.ACTION_POINTER_DOWN -> handlePointerDown(event)
            MotionEvent.ACTION_MOVE -> handleMove(event)
            MotionEvent.ACTION_POINTER_UP -> handlePointerUp(event)
            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_CANCEL -> handleUpOrCancel(event)
            else -> {
                if (
                    !panModeActive &&
                    !twoFingerHoldActive &&
                    twoFingerIntent == TwoFingerIntent.UNDECIDED
                ) {
                    onMouseEvent(event)
                }
            }
        }
    }

    private fun handleDown(event: MotionEvent) {
        if (
            panModeActive &&
            event.x >= touchAreaWidth - PAN_EXIT_HIT_WIDTH_PX &&
            event.y <= PAN_EXIT_HIT_HEIGHT_PX
        ) {
            // The parent pointerInteropFilter receives the touch before the
            // Compose Button can reliably complete its click. Exit on DOWN
            // so the close action reacts to the very first tap.
            panExitPressed = false
            cancelTwoFingerHold()
            exitPanMode()
            return
        }

        panExitPressed = false

        if (panModeActive) {
            lastPanX = event.x
            lastPanY = event.y
            return
        }

        onMouseEvent(event)
    }

    private fun handlePointerDown(event: MotionEvent) {
        if (event.pointerCount < 2) return

        val focusX = calculateFocusX(event)
        val focusY = calculateFocusY(event)
        val span = calculateSpan(event)

        if (panModeActive) {
            /*
             * In PAN MODE two fingers have two possible intentions:
             *
             *   hold still ~1s -> EXIT PAN MODE
             *   start moving    -> SCROLL
             *
             * We therefore wait before forwarding the gesture as scroll.
             */
            cancelTwoFingerHold()

            twoFingerHoldActive = true
            twoFingerIntent = TwoFingerIntent.UNDECIDED
            scrollForwarding = false

            holdStartX = focusX
            holdStartY = focusY
            lastSpan = span

            handler.removeCallbacks(exitPanModeRunnable)
            handler.postDelayed(
                exitPanModeRunnable,
                PAN_MODE_HOLD_MS
            )

            return
        }

        /*
         * The first finger is no longer allowed to become a long press.
         * Cancel the existing mouse gesture immediately.
         */
        cancelUnderlyingInput(event)

        twoFingerHoldActive = true
        twoFingerIntent = TwoFingerIntent.UNDECIDED
        scrollForwarding = false

        holdStartX = focusX
        holdStartY = focusY
        lastSpan = span

        handler.removeCallbacks(enterPanModeRunnable)
        handler.postDelayed(
            enterPanModeRunnable,
            PAN_MODE_HOLD_MS
        )
    }

    private fun handleMove(event: MotionEvent) {
        if (panModeActive) {
            handlePanModeMove(event)
            return
        }

        if (event.pointerCount >= 2) {
            handleTwoFingerMove(event)
            return
        }

        if (twoFingerHoldActive) return

        onMouseEvent(event)
    }

    private fun handlePanModeMove(event: MotionEvent) {
        if (event.pointerCount == 1) {
            val x = event.x
            val y = event.y

            onAction(
                Action.Pan(
                    dx = x - lastPanX,
                    dy = y - lastPanY
                )
            )

            lastPanX = x
            lastPanY = y
            return
        }

        if (event.pointerCount >= 2) {
            val focusX = calculateFocusX(event)
            val focusY = calculateFocusY(event)
            val span = calculateSpan(event)

            if (twoFingerIntent == TwoFingerIntent.UNDECIDED) {
                val focusDelta = hypot(
                    focusX - holdStartX,
                    focusY - holdStartY
                )
                val spanDelta = abs(span - lastSpan)

                val movementIsDominant =
                    focusDelta >= SCROLL_INTENT_THRESHOLD &&
                            focusDelta >= spanDelta * INTENT_DOMINANCE_RATIO

                // Any clearly intentional movement cancels the exit hold and
                // turns the gesture into the normal two-finger scroll.
                if (movementIsDominant) {
                    cancelTwoFingerHold()
                    twoFingerIntent = TwoFingerIntent.SCROLL
                    scrollForwarding = true

                    val startEvent =
                        MotionEvent.obtain(event).apply {
                            action = MotionEvent.ACTION_POINTER_DOWN
                        }

                    onMouseEvent(startEvent)
                    startEvent.recycle()

                    onMouseEvent(event)
                }

                lastSpan = span
                return
            }

            if (twoFingerIntent == TwoFingerIntent.SCROLL) {
                onMouseEvent(event)
                lastSpan = span
            }
        }
    }

    private fun handleTwoFingerMove(event: MotionEvent) {
        val focusX = calculateFocusX(event)
        val focusY = calculateFocusY(event)
        val span = calculateSpan(event)

        when (twoFingerIntent) {
            TwoFingerIntent.UNDECIDED -> {
                val focusDelta = hypot(
                    focusX - holdStartX,
                    focusY - holdStartY
                )

                val spanDelta = abs(span - lastSpan)

                /*
                 * Do not decide from a tiny distance change alone.
                 * During a real two-finger scroll the fingers naturally
                 * change their spacing by a few pixels. Zoom wins only when
                 * the spacing change is both large enough AND clearly
                 * stronger than the movement of the gesture's center.
                 */
                val pinchIsDominant =
                    spanDelta >= PINCH_INTENT_THRESHOLD &&
                            spanDelta >= focusDelta * INTENT_DOMINANCE_RATIO

                val scrollIsDominant =
                    focusDelta >= SCROLL_INTENT_THRESHOLD &&
                            focusDelta >= spanDelta * INTENT_DOMINANCE_RATIO

                if (pinchIsDominant) {
                    cancelTwoFingerHold()
                    twoFingerIntent = TwoFingerIntent.PINCH
                    lastPinchFocusX = focusX
                    lastPinchFocusY = focusY
                    lastSpan = span
                    return
                }

                if (scrollIsDominant) {
                    cancelTwoFingerHold()
                    twoFingerIntent = TwoFingerIntent.SCROLL

                    /*
                     * PointerInputRouter expects the beginning of a
                     * two-finger gesture. We intentionally synthesize only
                     * that start event after the intent is known.
                     */
                    val startEvent =
                        MotionEvent.obtain(event).apply {
                            action = MotionEvent.ACTION_POINTER_DOWN
                        }

                    onMouseEvent(startEvent)
                    startEvent.recycle()
                    onMouseEvent(event)

                    lastSpan = span
                    return
                }
            }

            TwoFingerIntent.PINCH -> {
                lastPinchFocusX = focusX
                lastPinchFocusY = focusY

                if (lastSpan > 0f) {
                    onAction(
                        Action.Zoom(
                            factor = span / lastSpan,
                            focusX = focusX,
                            focusY = focusY
                        )
                    )
                }

                lastSpan = span
                return
            }

            TwoFingerIntent.SCROLL -> {
                onMouseEvent(event)
                lastSpan = span
                return
            }
        }
    }

    private fun handlePointerUp(event: MotionEvent) {
        if (panModeActive) {
            if (twoFingerHoldActive) {
                cancelTwoFingerHold()
                twoFingerIntent = TwoFingerIntent.UNDECIDED
                lastSpan = 0f
            }

            if (scrollForwarding) {
                cancelUnderlyingInput(event)
                scrollForwarding = false
            }

            if (event.pointerCount == 2) {
                val remainingIndex =
                    if (event.actionIndex == 0) 1 else 0

                if (remainingIndex < event.pointerCount) {
                    lastPanX = event.getX(remainingIndex)
                    lastPanY = event.getY(remainingIndex)
                }
            }

            return
        }

        if (
            twoFingerIntent == TwoFingerIntent.SCROLL &&
            scrollForwarding
        ) {
            cancelUnderlyingInput(event)
            scrollForwarding = false
        }

        // A pinch is finished when one of its two fingers leaves.
        // Tell the controller so it can optionally recenter the real mouse
        // after a sufficiently large zoom.
        if (twoFingerIntent == TwoFingerIntent.PINCH) {
            onAction(
                Action.ZoomEnd(
                    focusX = lastPinchFocusX,
                    focusY = lastPinchFocusY
                )
            )
        }

        cancelTwoFingerHold()
        twoFingerIntent = TwoFingerIntent.UNDECIDED
        lastSpan = 0f
    }

    private fun handleUpOrCancel(event: MotionEvent) {
        if (panExitPressed) {
            panExitPressed = false
            exitPanMode()
            return
        }

        if (panModeActive) {
            cancelTwoFingerHold()
            return
        }

        if (
            twoFingerIntent == TwoFingerIntent.PINCH
        ) {
            onAction(
                Action.ZoomEnd(
                    focusX = lastPinchFocusX,
                    focusY = lastPinchFocusY
                )
            )
        } else if (
            scrollForwarding ||
            twoFingerIntent == TwoFingerIntent.SCROLL
        ) {
            cancelUnderlyingInput(event)
            scrollForwarding = false
        } else if (
            !twoFingerHoldActive &&
            twoFingerIntent != TwoFingerIntent.PINCH
        ) {
            onMouseEvent(event)
        }

        cancelTwoFingerHold()
        twoFingerIntent = TwoFingerIntent.UNDECIDED
        lastSpan = 0f
    }

    fun exitPanMode() {
        cancelTwoFingerHold()
        panModeActive = false
        twoFingerIntent = TwoFingerIntent.UNDECIDED
        scrollForwarding = false
        lastSpan = 0f
        lastPanX = 0f
        lastPanY = 0f
        panExitPressed = false

        onAction(Action.ExitPanMode)
    }

    private fun cancelTwoFingerHold() {
        twoFingerHoldActive = false
        handler.removeCallbacks(enterPanModeRunnable)
        handler.removeCallbacks(exitPanModeRunnable)
    }

    private fun cancelUnderlyingInput(event: MotionEvent) {
        val cancel = MotionEvent.obtain(event)
        cancel.action = MotionEvent.ACTION_CANCEL
        onMouseEvent(cancel)
        cancel.recycle()
    }

    fun dispose() {
        handler.removeCallbacks(enterPanModeRunnable)
        handler.removeCallbacks(exitPanModeRunnable)
    }

    private fun calculateSpan(event: MotionEvent): Float {
        if (event.pointerCount < 2) return 0f

        val dx = event.getX(0) - event.getX(1)
        val dy = event.getY(0) - event.getY(1)

        return hypot(dx, dy)
    }

    private fun calculateFocusX(event: MotionEvent): Float {
        if (event.pointerCount < 2) return 0f

        return (event.getX(0) + event.getX(1)) / 2f
    }

    private fun calculateFocusY(event: MotionEvent): Float {
        if (event.pointerCount < 2) return 0f

        return (event.getY(0) + event.getY(1)) / 2f
    }

    companion object {
        private const val PAN_MODE_HOLD_MS = 1000L
        private const val PINCH_INTENT_THRESHOLD = 12f
        private const val SCROLL_INTENT_THRESHOLD = 10f

        // The winning signal should be at least 25% stronger than the
        // competing signal before the gesture is locked to that intent.
        private const val INTENT_DOMINANCE_RATIO = 1.25f

        // Generous invisible hit target around the visual X button.
        // The actual Compose button can remain visually small.
        private const val PAN_EXIT_HIT_WIDTH_PX = 180f
        private const val PAN_EXIT_HIT_HEIGHT_PX = 140f
    }
}