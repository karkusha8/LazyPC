package com.example.lazypc.ui.screens

import android.content.res.Configuration
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
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.draw.clipToBounds
import com.example.lazypc.input.keyboard.core.KeyboardEngine
import com.example.lazypc.input.keyboard.emit.KeyboardEmitter
import com.example.lazypc.input.keyboard.ui.KeyboardScreen
import com.example.lazypc.input.mouse.CursorState
import com.example.lazypc.ui.components.BottomToolbar
import com.example.lazypc.video.CustomVideoRenderer
import com.example.lazypc.video.ScreenViewport
import com.example.lazypc.video.VideoGestureController
import org.webrtc.EglBase
import kotlin.math.roundToInt

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
    onRecenterMouse: (Float, Float) -> Unit,
    onMouseActionBoundsChanged: (Float, Float, Float, Float) -> Unit,
    keyboardEngine: KeyboardEngine,
    keyboardEmitter: KeyboardEmitter,
    onDragModeChanged: (Boolean) -> Unit
) {
    var keyboardVisible by remember { mutableStateOf(false) }
    var dragModeEnabled by remember { mutableStateOf(false) }
    var panModeActive by remember { mutableStateOf(false) }

    val viewport = remember { ScreenViewport() }

    val gestureController = remember(viewport) {
        VideoGestureController(
            viewport = viewport,
            onMouseEvent = onTouch,
            onPanModeChanged = { active ->
                panModeActive = active
            },
            onRecenterMouse = onRecenterMouse
        )
    }

    DisposableEffect(gestureController) {
        onDispose {
            gestureController.dispose()
        }
    }

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

    /*
     * Current valid mouse-action area in fitted-video coordinates.
     * At 1x it is the whole fitted video. When zoomed, it becomes only
     * the part of the source that is currently visible inside the fixed Box.
     */
    LaunchedEffect(
        viewport.scale,
        viewport.offsetX,
        viewport.offsetY,
        viewport.fittedWidth,
        viewport.fittedHeight
    ) {
        val width = viewport.fittedWidth
        val height = viewport.fittedHeight

        if (width <= 0f || height <= 0f) {
            return@LaunchedEffect
        }

        val scale = viewport.scale.coerceAtLeast(0.0001f)
        val centerX = width / 2f
        val centerY = height / 2f

        val minX = (
                centerX +
                        (0f - centerX - viewport.offsetX) / scale
                ).coerceIn(0f, width)

        val maxX = (
                centerX +
                        (width - centerX - viewport.offsetX) / scale
                ).coerceIn(0f, width)

        val minY = (
                centerY +
                        (0f - centerY - viewport.offsetY) / scale
                ).coerceIn(0f, height)

        val maxY = (
                centerY +
                        (height - centerY - viewport.offsetY) / scale
                ).coerceIn(0f, height)

        onMouseActionBoundsChanged(
            minOf(minX, maxX),
            maxOf(minX, maxX),
            minOf(minY, maxY),
            maxOf(minY, maxY)
        )
    }

    fun updateViewportSize(width: Int, height: Int) {
        viewport.setViewportSize(
            width.toFloat(),
            height.toFloat()
        )

        gestureController.updateTouchAreaSize(
            width.toFloat(),
            height.toFloat()
        )

        onMouseAreaSizeChanged(
            width.toFloat(),
            height.toFloat()
        )
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
                    gestureController.handleTouch(it)
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
                onExit = {
                    gestureController.exitPanMode()
                }
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

/**
 * The Compose viewport is fixed.
 *
 * The outer screen area fills the available space.
 * The fitted video Box has a fixed layout size.
 * Zoom/pan are applied only through CustomVideoRenderer.setContentTransform().
 *
 * The fitted video Box is clipped so a transformed TextureView can never
 * visually enlarge the box itself.
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
                        renderer.setContentTransform(
                            scale = viewport.scale,
                            offsetX = viewport.offsetX,
                            offsetY = viewport.offsetY
                        )
                    }
                )

                LocalCursor(
                    modifier = Modifier.fillMaxSize(),
                    cursorState = cursorState,
                    cursorScale = cursorScale,
                    viewport = viewport
                )
            }
        }
    }
}

@Composable
private fun LocalCursor(
    modifier: Modifier = Modifier,
    cursorState: CursorState,
    cursorScale: Float = 1f,
    viewport: ScreenViewport
) {
    Canvas(
        modifier = modifier.fillMaxSize()
    ) {
        val s = cursorScale

        /*
         * CursorState stores the real mouse position in the original
         * fitted-video coordinate system.
         *
         * The video content is transformed around the center of the
         * fixed video Box. Apply the exact same transform to the cursor.
         */
        val boxWidth = viewport.fittedWidth
        val boxHeight = viewport.fittedHeight

        val centerX = boxWidth / 2f
        val centerY = boxHeight / 2f

        val cursorX =
            (cursorState.x - centerX) * viewport.scale +
                    centerX +
                    viewport.offsetX

        val cursorY =
            (cursorState.y - centerY) * viewport.scale +
                    centerY +
                    viewport.offsetY

        val path =
            Path().apply {
                moveTo(
                    cursorX,
                    cursorY
                )

                lineTo(
                    cursorX,
                    cursorY + 34f * s
                )

                lineTo(
                    cursorX + 10f * s,
                    cursorY + 25f * s
                )

                lineTo(
                    cursorX + 17f * s,
                    cursorY + 40f * s
                )

                lineTo(
                    cursorX + 23f * s,
                    cursorY + 37f * s
                )

                lineTo(
                    cursorX + 16f * s,
                    cursorY + 23f * s
                )

                lineTo(
                    cursorX + 30f * s,
                    cursorY + 23f * s
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