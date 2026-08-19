package com.example.lazypc.ui.screens

import android.content.res.Configuration
import android.view.MotionEvent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
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
import com.example.lazypc.ScreenSurfaceView
import com.example.lazypc.input.CursorState
import com.example.lazypc.keyboard.core.KeyboardEngine
import com.example.lazypc.keyboard.emit.KeyboardEmitter
import com.example.lazypc.keyboard.ui.KeyboardScreen
import com.example.lazypc.ui.components.BottomToolbar
import org.webrtc.EglBase
import org.webrtc.RendererCommon
import org.webrtc.SurfaceViewRenderer

@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun RootScreen(

    eglContext: EglBase.Context,

    videoWidth: Int,
    videoHeight: Int,

    onSurfaceCreated:
        (SurfaceViewRenderer) -> Unit,

    onTouch:
        (MotionEvent) -> Unit,

    cursorState:
    CursorState,

    onMouseAreaSizeChanged:
        (Float, Float) -> Unit,

    onVideoAreaSizeChanged:
        (Float, Float) -> Unit,

    keyboardEngine:
    KeyboardEngine,

    keyboardEmitter:
    KeyboardEmitter,

    onDragModeChanged:
        (Boolean) -> Unit
) {

    var keyboardVisible by remember {
        mutableStateOf(false)
    }

    var dragModeEnabled by remember {
        mutableStateOf(false)
    }

    val configuration =
        LocalConfiguration.current

    val isLandscape =
        configuration.orientation ==
                Configuration.ORIENTATION_LANDSCAPE

    /*
     * ================================================================
     * REAL VIDEO ASPECT RATIO
     *
     * Пока WebRTC ещё не прислал первый кадр,
     * используем 16:9 только как временный стартовый fallback.
     *
     * После первого кадра здесь будет реальное:
     *
     * 1920 / 1080
     * 1366 / 768
     * 1280 / 1024
     * и т.д.
     * ================================================================
     */

    val videoAspectRatio =
        if (
            videoWidth > 0 &&
            videoHeight > 0
        ) {
            videoWidth.toFloat() /
                    videoHeight.toFloat()
        } else {
            16f / 9f
        }

    // ================================================================
    // LANDSCAPE
    // ================================================================

    if (isLandscape) {

        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
        ) {

            // ========================================================
            // VIDEO
            // ========================================================

            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(
                        if (keyboardVisible) {
                            0.40f
                        } else {
                            1f
                        }
                    )
                    .background(Color.Black)
                    .pointerInteropFilter { event ->

                        onTouch(event)

                        true
                    },

                contentAlignment =
                    Alignment.Center
            ) {

                Box(
                    modifier = Modifier
                        .fillMaxHeight()
                        .aspectRatio(
                            videoAspectRatio
                        )
                        .background(Color.Black)
                        .onSizeChanged { size ->

                            onMouseAreaSizeChanged(
                                size.width.toFloat(),
                                size.height.toFloat()
                            )

                            onVideoAreaSizeChanged(
                                size.width.toFloat(),
                                size.height.toFloat()
                            )
                        }
                ) {

                    ScreenSurfaceView(
                        modifier =
                            Modifier.fillMaxSize(),

                        eglContext =
                            eglContext,

                        onSurfaceReady =
                            onSurfaceCreated,

                        scalingType =
                            RendererCommon.ScalingType
                                .SCALE_ASPECT_FIT
                    )

                    LocalCursor(
                        cursorState =
                            cursorState,

                        cursorScale =
                            0.8f
                    )
                }
            }

            // ========================================================
            // KEYBOARD
            // ========================================================

            if (keyboardVisible) {

                KeyboardScreen(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(0.60f),

                    keyboardEngine =
                        keyboardEngine,

                    keyboardEmitter =
                        keyboardEmitter
                )
            }

            // ========================================================
            // TOOLBAR
            // ========================================================

            BottomToolbar(

                keyboardVisible =
                    keyboardVisible,

                dragModeEnabled =
                    dragModeEnabled,

                onToggleKeyboard = {

                    keyboardVisible =
                        !keyboardVisible
                },

                onToggleDrag = {

                    dragModeEnabled =
                        !dragModeEnabled

                    onDragModeChanged(
                        dragModeEnabled
                    )
                }
            )
        }

        return
    }

    // ================================================================
    // PORTRAIT
    // ================================================================

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
    ) {

        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
                .onSizeChanged { size ->

                    onMouseAreaSizeChanged(
                        size.width.toFloat(),
                        size.height.toFloat()
                    )
                }
                .pointerInteropFilter { event ->

                    onTouch(event)

                    true
                }
        ) {

            Column(
                modifier =
                    Modifier.fillMaxSize()
            ) {

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(
                            videoAspectRatio
                        )
                        .onSizeChanged { size ->

                            onVideoAreaSizeChanged(
                                size.width.toFloat(),
                                size.height.toFloat()
                            )
                        }
                ) {

                    ScreenSurfaceView(
                        modifier =
                            Modifier.fillMaxSize(),

                        eglContext =
                            eglContext,

                        onSurfaceReady =
                            onSurfaceCreated,

                        scalingType =
                            RendererCommon.ScalingType
                                .SCALE_ASPECT_FIT
                    )

                    LocalCursor(
                        cursorState =
                            cursorState,

                        cursorScale =
                            0.7f
                    )
                }

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .background(Color.Black)
                )
            }
        }

        if (keyboardVisible) {

            KeyboardScreen(
                modifier =
                    Modifier.fillMaxHeight(0.4f),

                keyboardEngine =
                    keyboardEngine,

                keyboardEmitter =
                    keyboardEmitter
            )
        }

        BottomToolbar(

            keyboardVisible =
                keyboardVisible,

            dragModeEnabled =
                dragModeEnabled,

            onToggleKeyboard = {

                keyboardVisible =
                    !keyboardVisible
            },

            onToggleDrag = {

                dragModeEnabled =
                    !dragModeEnabled

                onDragModeChanged(
                    dragModeEnabled
                )
            }
        )
    }
}

@Composable
private fun LocalCursor(
    cursorState: CursorState,
    cursorScale: Float = 1f
) {

    Canvas(
        modifier =
            Modifier.fillMaxSize()
    ) {

        val s =
            cursorScale

        val path =
            Path().apply {

                moveTo(
                    cursorState.x,
                    cursorState.y
                )

                lineTo(
                    cursorState.x,
                    cursorState.y +
                            34f * s
                )

                lineTo(
                    cursorState.x +
                            10f * s,
                    cursorState.y +
                            25f * s
                )

                lineTo(
                    cursorState.x +
                            17f * s,
                    cursorState.y +
                            40f * s
                )

                lineTo(
                    cursorState.x +
                            23f * s,
                    cursorState.y +
                            37f * s
                )

                lineTo(
                    cursorState.x +
                            16f * s,
                    cursorState.y +
                            23f * s
                )

                lineTo(
                    cursorState.x +
                            30f * s,
                    cursorState.y +
                            23f * s
                )

                close()
            }

        drawPath(
            path = path,
            color = Color.Black,
            style = Stroke(
                width = 4f * s
            )
        )

        drawPath(
            path = path,
            color = Color.White
        )
    }
}