package com.example.lazypc.ui.screens

import android.content.res.Configuration
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.example.lazypc.input.keyboard.core.KeyboardEngine
import com.example.lazypc.input.keyboard.emit.KeyboardEmitter
import com.example.lazypc.input.keyboard.ui.KeyboardScreen
import com.example.lazypc.input.mouse.CursorState
import com.example.lazypc.ui.components.BottomToolbar
import com.example.lazypc.video.CustomVideoRenderer
import com.example.lazypc.video.ScreenViewport
import org.webrtc.EglBase
import kotlin.math.hypot
import kotlin.math.roundToInt
import androidx.compose.ui.draw.clipToBounds

private const val PAN_MODE_HOLD_MS = 1200L
private const val PAN_MODE_MOVE_THRESHOLD = 12f

@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun RootScreen(
    eglContext: EglBase.Context,
    videoWidth: Int,
    videoHeight: Int,
    onSurfaceCreated: (CustomVideoRenderer) -> Unit,
    onTouch: (MotionEvent) -> Unit,
    cursorState: CursorState,
    onMouseAreaSizeChanged: (Float, Float) -> Unit,
    onVideoAreaSizeChanged: (Float, Float) -> Unit,
    keyboardEngine: KeyboardEngine,
    keyboardEmitter: KeyboardEmitter,
    onDragModeChanged: (Boolean) -> Unit
) {
    var keyboardVisible by remember { mutableStateOf(false) }
    var dragModeEnabled by remember { mutableStateOf(false) }

    val viewport = remember { ScreenViewport() }

    val isLandscape =
        LocalConfiguration.current.orientation ==
                Configuration.ORIENTATION_LANDSCAPE

    LaunchedEffect(videoWidth, videoHeight) {
        if (videoWidth > 0 && videoHeight > 0) {
            viewport.setVideoSize(
                videoWidth.toFloat(),
                videoHeight.toFloat()
            )
        }
    }

    fun updateViewportSize(width: Int, height: Int) {
        viewport.setViewportSize(
            width.toFloat(),
            height.toFloat()
        )

        onMouseAreaSizeChanged(
            width.toFloat(),
            height.toFloat()
        )
    }

    var transformActive by remember { mutableStateOf(false) }
    var panModeActive by remember { mutableStateOf(false) }
    var twoFingerHoldActive by remember { mutableStateOf(false) }

    var holdStartX by remember { mutableFloatStateOf(0f) }
    var holdStartY by remember { mutableFloatStateOf(0f) }

    var lastPanX by remember { mutableFloatStateOf(0f) }
    var lastPanY by remember { mutableFloatStateOf(0f) }

    var lastSpan by remember { mutableFloatStateOf(0f) }
    var lastFocusX by remember { mutableFloatStateOf(0f) }
    var lastFocusY by remember { mutableFloatStateOf(0f) }

    var panExitPressed by remember { mutableStateOf(false) }

    val density = LocalDensity.current
    val panExitHitWidthPx = with(density) { 110.dp.toPx() }
    val panExitHitHeightPx = with(density) { 90.dp.toPx() }

    val panModeHandler = remember { Handler(Looper.getMainLooper()) }
    var togglePanModeOnHold by remember { mutableStateOf(false) }

    val enterPanModeRunnable = remember {
        Runnable {
            if (!twoFingerHoldActive) return@Runnable

            if (togglePanModeOnHold) {
                panModeActive = false
                transformActive = false
            } else {
                panModeActive = true
                transformActive = false
            }

            twoFingerHoldActive = false
            lastSpan = 0f
            lastFocusX = 0f
            lastFocusY = 0f
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            panModeHandler.removeCallbacks(
                enterPanModeRunnable
            )
        }
    }

    fun cancelPanModeHold() {
        twoFingerHoldActive = false
        panModeHandler.removeCallbacks(
            enterPanModeRunnable
        )
    }

    fun exitPanMode() {
        cancelPanModeHold()
        panModeActive = false
        transformActive = false
        lastSpan = 0f
        lastFocusX = 0f
        lastFocusY = 0f
        lastPanX = 0f
        lastPanY = 0f
        panExitPressed = false
        togglePanModeOnHold = false
    }

    fun handleTouch(event: MotionEvent) {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                if (
                    panModeActive &&
                    event.x >=
                    viewport.viewportWidth - panExitHitWidthPx &&
                    event.y <= panExitHitHeightPx
                ) {
                    panExitPressed = true
                    cancelPanModeHold()
                    return
                }

                panExitPressed = false
                holdStartX = event.x
                holdStartY = event.y

                if (panModeActive) {
                    lastPanX = event.x
                    lastPanY = event.y
                    return
                }

                onTouch(event)
            }

            MotionEvent.ACTION_POINTER_DOWN -> {
                if (event.pointerCount < 2) return

                if (!panModeActive) {
                    val cancelEvent =
                        MotionEvent.obtain(event).apply {
                            action = MotionEvent.ACTION_CANCEL
                        }

                    onTouch(cancelEvent)
                    cancelEvent.recycle()
                }

                val focusX = calculateFocusX(event)
                val focusY = calculateFocusY(event)

                twoFingerHoldActive = true
                togglePanModeOnHold = panModeActive

                holdStartX = focusX
                holdStartY = focusY

                transformActive = false
                lastSpan = calculateSpan(event)
                lastFocusX = focusX
                lastFocusY = focusY

                panModeHandler.removeCallbacks(
                    enterPanModeRunnable
                )

                panModeHandler.postDelayed(
                    enterPanModeRunnable,
                    PAN_MODE_HOLD_MS
                )
            }

            MotionEvent.ACTION_MOVE -> {
                if (panModeActive) {
                    if (event.pointerCount == 1) {
                        val x = event.x
                        val y = event.y

                        viewport.panBy(
                            dx = x - lastPanX,
                            dy = y - lastPanY
                        )

                        lastPanX = x
                        lastPanY = y
                    } else if (event.pointerCount >= 2) {
                        val focusX = calculateFocusX(event)
                        val focusY = calculateFocusY(event)
                        val span = calculateSpan(event)

                        if (twoFingerHoldActive) {
                            if (
                                hypot(
                                    focusX - holdStartX,
                                    focusY - holdStartY
                                ) > PAN_MODE_MOVE_THRESHOLD
                            ) {
                                cancelPanModeHold()
                            }
                        }

                        if (lastSpan > 0f) {
                            viewport.zoomAt(
                                factor = span / lastSpan,
                                focusX = focusX,
                                focusY = focusY
                            )
                        }

                        viewport.panBy(
                            dx = focusX - lastFocusX,
                            dy = focusY - lastFocusY
                        )

                        lastSpan = span
                        lastFocusX = focusX
                        lastFocusY = focusY
                    }

                    return
                }

                if (
                    twoFingerHoldActive &&
                    event.pointerCount >= 2
                ) {
                    val focusX = calculateFocusX(event)
                    val focusY = calculateFocusY(event)

                    if (
                        hypot(
                            focusX - holdStartX,
                            focusY - holdStartY
                        ) > PAN_MODE_MOVE_THRESHOLD
                    ) {
                        cancelPanModeHold()

                        transformActive = true
                        lastSpan = calculateSpan(event)
                        lastFocusX = focusX
                        lastFocusY = focusY
                    }
                }

                if (
                    transformActive &&
                    event.pointerCount >= 2
                ) {
                    val span = calculateSpan(event)
                    val focusX = calculateFocusX(event)
                    val focusY = calculateFocusY(event)

                    if (lastSpan > 0f) {
                        viewport.zoomAt(
                            factor = span / lastSpan,
                            focusX = focusX,
                            focusY = focusY
                        )
                    }

                    viewport.panBy(
                        dx = focusX - lastFocusX,
                        dy = focusY - lastFocusY
                    )

                    lastSpan = span
                    lastFocusX = focusX
                    lastFocusY = focusY

                    return
                }

                if (!twoFingerHoldActive) {
                    onTouch(event)
                }
            }

            MotionEvent.ACTION_POINTER_UP -> {
                if (panModeActive) {
                    cancelPanModeHold()

                    if (event.pointerCount == 2) {
                        val remainingIndex =
                            if (event.actionIndex == 0) 1 else 0

                        if (remainingIndex < event.pointerCount) {
                            lastPanX =
                                event.getX(remainingIndex)
                            lastPanY =
                                event.getY(remainingIndex)
                        }
                    }

                    return
                }

                cancelPanModeHold()
                transformActive = false
                lastSpan = 0f
            }

            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_CANCEL -> {
                if (panExitPressed) {
                    panExitPressed = false
                    exitPanMode()
                    return
                }

                if (panModeActive) {
                    cancelPanModeHold()
                    return
                }

                if (
                    !twoFingerHoldActive &&
                    !transformActive
                ) {
                    onTouch(event)
                }

                cancelPanModeHold()
                transformActive = false
                lastSpan = 0f
            }

            else -> {
                if (
                    !panModeActive &&
                    !twoFingerHoldActive &&
                    !transformActive
                ) {
                    onTouch(event)
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(
                    if (isLandscape && keyboardVisible) {
                        0.40f
                    } else {
                        1f
                    }
                )
                .background(Color.Black)
                .onSizeChanged { size ->
                    updateViewportSize(
                        size.width,
                        size.height
                    )
                }
                .pointerInteropFilter {
                    handleTouch(it)
                    true
                }
        ) {
            VideoViewport(
                viewport = viewport,
                eglContext = eglContext,
                onSurfaceCreated = onSurfaceCreated,
                cursorState = cursorState,
                cursorScale =
                    if (isLandscape) 0.8f else 0.7f,
                onVideoAreaSizeChanged =
                    onVideoAreaSizeChanged
            )

            PanModeOverlay(
                visible = panModeActive,
                onExit = { exitPanMode() }
            )
        }

        if (keyboardVisible) {
            KeyboardScreen(
                modifier =
                    if (isLandscape) {
                        Modifier
                            .fillMaxWidth()
                            .weight(0.60f)
                    } else {
                        Modifier.fillMaxHeight(0.40f)
                    },
                keyboardEngine = keyboardEngine,
                keyboardEmitter = keyboardEmitter
            )
        }

        BottomToolbar(
            keyboardVisible = keyboardVisible,
            dragModeEnabled = dragModeEnabled,
            onToggleKeyboard = {
                keyboardVisible = !keyboardVisible
            },
            onToggleDrag = {
                dragModeEnabled = !dragModeEnabled
                onDragModeChanged(dragModeEnabled)
            }
        )
    }
}

@Composable
private fun PanModeOverlay(
    visible: Boolean,
    onExit: () -> Unit
) {
    if (!visible) return

    Box(
        modifier = Modifier
            .fillMaxSize()
            .border(
                width = 4.dp,
                color = Color.Red,
                shape = RoundedCornerShape(0.dp)
            )
    ) {
        Row(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Box(
                modifier = Modifier
                    .background(
                        Color.Red,
                        RoundedCornerShape(10.dp)
                    )
                    .padding(
                        horizontal = 12.dp,
                        vertical = 7.dp
                    )
            ) {
                Text(
                    text = "ПЕРЕМЕЩЕНИЕ",
                    color = Color.White
                )
            }

            Spacer(Modifier.width(8.dp))

            Button(onClick = onExit) {
                Text("✕")
            }
        }
    }
}

/*
 * Fixed viewport:
 *
 *   OUTER BOX (static, fills available screen)
 *       CONTENT BOX (fitted video size)
 *           TextureView (WebRTC renderer)
 *           cursor
 *
 * Only CONTENT BOX is transformed. Therefore zoom cannot change the
 * size or position of the outer viewport.
 */
@Composable
private fun VideoViewport(
    viewport: ScreenViewport,
    eglContext: EglBase.Context,
    onSurfaceCreated: (CustomVideoRenderer) -> Unit,
    cursorState: CursorState,
    cursorScale: Float,
    onVideoAreaSizeChanged: (Float, Float) -> Unit
) {
    val fittedWidth = viewport.fittedWidth.roundToInt()
    val fittedHeight = viewport.fittedHeight.roundToInt()

    LaunchedEffect(
        fittedWidth,
        fittedHeight
    ) {
        if (
            fittedWidth > 0 &&
            fittedHeight > 0
        ) {
            onVideoAreaSizeChanged(
                fittedWidth.toFloat(),
                fittedHeight.toFloat()
            )
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .clipToBounds()
    ) {

        if (
            fittedWidth > 0 &&
            fittedHeight > 0
        ) {

            /*
             * FIXED VIDEO WINDOW
             *
             * Этот Box НИКОГДА не масштабируется.
             * Его размер всегда равен исходному fitted video size.
             */
            Box(
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .width(
                        with(LocalDensity.current) {
                            fittedWidth.toDp()
                        }
                    )
                    .height(
                        with(LocalDensity.current) {
                            fittedHeight.toDp()
                        }
                    )
                    .clipToBounds()
            ) {

                /*
                 * WebRTC renderer.
                 *
                 * ВАЖНО:
                 * AndroidView остаётся абсолютно фиксированного размера.
                 *
                 * Zoom теперь НЕ применяется к AndroidView.
                 *
                 * Мы передаём transform непосредственно
                 * внутрь TextureView через CustomVideoRenderer.
                 */
                AndroidView(
                    modifier = Modifier.fillMaxSize(),

                    factory = { context ->
                        CustomVideoRenderer(context).apply {
                            initRenderer(eglContext)
                            onSurfaceCreated(this)

                            setContentTransform(
                                scale = 1f,
                                offsetX = 0f,
                                offsetY = 0f
                            )
                        }
                    },

                    update = { renderer ->

                        /*
                         * КРИТИЧЕСКИ ВАЖНО:
                         *
                         * renderer НЕ меняет свой размер.
                         *
                         * renderer НЕ получает graphicsLayer.
                         *
                         * renderer НЕ масштабируется как Android View.
                         *
                         * Меняется только содержимое TextureView.
                         */
                        renderer.setContentTransform(
                            scale = viewport.scale,
                            offsetX = viewport.offsetX,
                            offsetY = viewport.offsetY
                        )
                    }
                )

                /*
                 * Курсор остаётся поверх видео.
                 */
                LocalCursor(
                    modifier = Modifier.fillMaxSize(),
                    cursorState = cursorState,
                    cursorScale = cursorScale
                )
            }
        }
    }
}

private fun calculateSpan(
    event: MotionEvent
): Float {
    if (event.pointerCount < 2) return 0f

    val dx =
        event.getX(0) - event.getX(1)

    val dy =
        event.getY(0) - event.getY(1)

    return hypot(dx, dy)
}

private fun calculateFocusX(
    event: MotionEvent
): Float {
    if (event.pointerCount < 2) return 0f

    return (
            event.getX(0) +
                    event.getX(1)
            ) / 2f
}

private fun calculateFocusY(
    event: MotionEvent
): Float {
    if (event.pointerCount < 2) return 0f

    return (
            event.getY(0) +
                    event.getY(1)
            ) / 2f
}

@Composable
private fun LocalCursor(
    modifier: Modifier = Modifier,
    cursorState: CursorState,
    cursorScale: Float = 1f
) {
    Canvas(
        modifier = modifier.fillMaxSize()
    ) {
        val s = cursorScale

        val path =
            Path().apply {
                moveTo(
                    cursorState.x,
                    cursorState.y
                )

                lineTo(
                    cursorState.x,
                    cursorState.y + 34f * s
                )

                lineTo(
                    cursorState.x + 10f * s,
                    cursorState.y + 25f * s
                )

                lineTo(
                    cursorState.x + 17f * s,
                    cursorState.y + 40f * s
                )

                lineTo(
                    cursorState.x + 23f * s,
                    cursorState.y + 37f * s
                )

                lineTo(
                    cursorState.x + 16f * s,
                    cursorState.y + 23f * s
                )

                lineTo(
                    cursorState.x + 30f * s,
                    cursorState.y + 23f * s
                )

                close()
            }

        drawPath(
            path = path,
            color = Color.Black,
            style = Stroke(width = 4f * s)
        )

        drawPath(
            path = path,
            color = Color.White
        )
    }
}