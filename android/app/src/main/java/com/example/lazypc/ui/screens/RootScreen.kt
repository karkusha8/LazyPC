package com.example.lazypc.ui.screens

import androidx.compose.ui.Alignment
import android.content.res.Configuration
import android.view.MotionEvent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
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
import androidx.compose.ui.unit.dp


@OptIn(ExperimentalComposeUiApi::class)
@Composable
fun RootScreen(

    eglContext: EglBase.Context,

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
                        if (keyboardVisible) 0.40f else 1f
                    )
                    .background(Color.Black)
                    .pointerInteropFilter { event ->
                        onTouch(event)
                        true
                    },

                contentAlignment = Alignment.Center

            ) {

                Box(

                    modifier = Modifier
                        .fillMaxHeight()
                        .aspectRatio(16f / 9f)
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

                        modifier = Modifier.fillMaxSize(),

                        eglContext = eglContext,

                        onSurfaceReady = onSurfaceCreated,

                        scalingType = RendererCommon.ScalingType.SCALE_ASPECT_FIT
                    )

                    LocalCursor(

                        cursorState = cursorState,

                        cursorScale = 0.8f
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

                    keyboardEngine = keyboardEngine,

                    keyboardEmitter = keyboardEmitter
                )
            }


            // ========================================================
            // TOOLBAR
            // ========================================================

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

                        .aspectRatio(16f / 9f)

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
                            RendererCommon.ScalingType.SCALE_ASPECT_FIT
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

        modifier = Modifier.fillMaxSize()

    ) {


        val s = cursorScale


        val path = Path().apply {


            // Кончик стрелки Windows
            moveTo(
                cursorState.x,
                cursorState.y
            )


            // Левая сторона вниз
            lineTo(
                cursorState.x,
                cursorState.y + 34f * s
            )


            // Внутренний угол
            lineTo(
                cursorState.x + 10f * s,
                cursorState.y + 25f * s
            )


            // Нижняя часть ручки
            lineTo(
                cursorState.x + 17f * s,
                cursorState.y + 40f * s
            )


            // Нижний правый угол ручки
            lineTo(
                cursorState.x + 23f * s,
                cursorState.y + 37f * s
            )


            // Верх ручки
            lineTo(
                cursorState.x + 16f * s,
                cursorState.y + 23f * s
            )


            // Правая часть стрелки
            lineTo(
                cursorState.x + 30f * s,
                cursorState.y + 23f * s
            )


            // Закрываем стрелку
            close()
        }



        // Чёрная обводка
        drawPath(

            path = path,

            color = Color.Black,

            style = Stroke(

                width = 4f * s

            )
        )



        // Белая заливка
        drawPath(

            path = path,

            color = Color.White

        )
    }
}