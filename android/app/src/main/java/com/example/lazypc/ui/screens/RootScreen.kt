

import android.content.res.Configuration
import android.view.MotionEvent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
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
import com.example.lazypc.security.TrustedPc
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
    onDragModeChanged: (Boolean) -> Unit,
    sessionConnecting: Boolean,
    sessionConnected: Boolean,
    onConnectSession: () -> Unit,
    onDisconnectSession: () -> Unit,
    onAddTrustedDevice: () -> Unit,

    trustedPcs: List<TrustedPc> = emptyList(),
    onConnectTrustedPc: (TrustedPc) -> Unit = {},
    onRemoveTrustedPc: (TrustedPc) -> Unit = {},

    // New simplified connection model.
    // Wiring these callbacks to the service comes next.
    onConnectToPc: (String) -> Unit = {},
    onDisconnectToPc: () -> Unit = {},
    simpleConnectionConnecting: Boolean = false,
    simpleConnectionConnected: Boolean = false,
    simpleConnectionError: String? = null
) {
    var keyboardVisible by remember { mutableStateOf(false) }
    var dragModeEnabled by remember { mutableStateOf(false) }
    var panModeActive by remember { mutableStateOf(false) }

    var pcIdInput by remember { mutableStateOf("") }

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

        /*
         * SECOND CONNECTION MODEL
         *
         * This UI is deliberately independent from SessionControl below.
         * It does not replace or alter the existing connection model.
         */
        SimplePcConnectionControl(
            pcId = pcIdInput,
            onPcIdChanged = {
                // Keep only the ID itself here. Validation belongs to the
                // service/network layer.
                pcIdInput = it
            },
            connecting = simpleConnectionConnecting,
            connected = simpleConnectionConnected,
            error = simpleConnectionError,
            onConnect = {
                val normalized = pcIdInput.trim()
                if (normalized.isNotEmpty()) {
                    onConnectToPc(normalized)
                }
            },
            onDisconnect = onDisconnectToPc
        )

        TrustedPcConnectionControl(
            devices = trustedPcs,
            connecting = sessionConnecting,
            connected = sessionConnected,
            onConnect = onConnectTrustedPc,
            onDisconnect = onDisconnectSession,
            onRemove = onRemoveTrustedPc
        )

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

        Button(
            onClick = onAddTrustedDevice,
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
            colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                containerColor = Color(0xFF202020)
            )
        ) {
            Text(
                text = "ДОБАВИТЬ ДОВЕРЕННОЕ УСТРОЙСТВО",
                color = Color.White
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
private fun TrustedPcConnectionControl(
    devices: List<TrustedPc>,
    connecting: Boolean,
    connected: Boolean,
    onConnect: (TrustedPc) -> Unit,
    onDisconnect: () -> Unit,
    onRemove: (TrustedPc) -> Unit
) {
    var selected by remember(devices) {
        mutableStateOf(devices.firstOrNull())
    }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color.Black)
            .padding(horizontal = 12.dp, vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "ДОВЕРЕННЫЕ КОМПЬЮТЕРЫ",
            color = Color.White,
            modifier = Modifier.padding(bottom = 6.dp)
        )

        if (devices.isEmpty()) {
            Text(
                text = "Нет сопряжённых компьютеров",
                color = Color(0xFFAAAAAA),
                modifier = Modifier.padding(vertical = 8.dp)
            )
        } else {
            devices.forEach { pc ->
                val isSelected = selected?.pcCode == pc.pcCode
                Button(
                    onClick = { selected = pc },
                    enabled = !connecting && !connected,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 2.dp),
                    colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                        containerColor = if (isSelected) Color(0xFF303030) else Color(0xFF181818),
                        disabledContainerColor = if (isSelected) Color(0xFF303030) else Color(0xFF181818)
                    )
                ) {
                    Text(
                        text = "${if (isSelected) "●" else "○"}  ${pc.name}\n${formatPcCode(pc.pcCode)}",
                        color = Color.White
                    )
                }
            }
        }

        Spacer(Modifier.height(6.dp))

        Button(
            onClick = {
                if (connected) onDisconnect()
                else selected?.let(onConnect)
            },
            enabled = connected || (!connecting && selected != null),
            modifier = Modifier.fillMaxWidth().height(46.dp),
            colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                containerColor = if (connected) Color(0xFF8B1E1E) else Color(0xFF2C2C2C),
                disabledContainerColor = Color(0xFF202020)
            )
        ) {
            Text(
                text = when {
                    connected -> "ОТКЛЮЧИТЬСЯ"
                    connecting -> "ПОДКЛЮЧЕНИЕ..."
                    else -> "ПОДКЛЮЧИТЬСЯ"
                },
                color = Color.White
            )
        }

        if (selected != null && !connecting && !connected) {
            Button(
                onClick = { selected?.let(onRemove); selected = null },
                modifier = Modifier.fillMaxWidth().height(40.dp),
                colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                    containerColor = Color(0xFF202020)
                )
            ) {
                Text("УДАЛИТЬ ВЫБРАННЫЙ ПК", color = Color(0xFFFF8080))
            }
        }
    }
}

private fun formatPcCode(code: String): String {
    val normalized = code.filter { it.isDigit() }
    return if (normalized.length == 9) {
        "${normalized.substring(0, 3)} ${normalized.substring(3, 6)} ${normalized.substring(6, 9)}"
    } else normalized
}

/**
 * New simplified connection UI.
 *
 * It only collects a PC ID and invokes onConnectToPc().
 * Actual WebSocket/registry/WebRTC wiring is intentionally not here.
 */
@Composable
private fun SimplePcConnectionControl(
    pcId: String,
    onPcIdChanged: (String) -> Unit,
    connecting: Boolean,
    connected: Boolean,
    error: String?,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color.Black)
            .padding(
                horizontal = 12.dp,
                vertical = 6.dp
            ),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        OutlinedTextField(
            value = pcId,
            onValueChange = onPcIdChanged,
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            enabled = !connecting && !connected,
            label = {
                Text("ID компьютера")
            },
            placeholder = {
                Text("Например: lazypc-123456")
            },
            supportingText = {
                when {
                    error != null -> {
                        Text(
                            text = error,
                            color = Color(0xFFFF6B6B)
                        )
                    }

                    connected -> {
                        Text(
                            text = "Подключено",
                            color = Color(0xFF66BB6A)
                        )
                    }

                    connecting -> {
                        Text(
                            text = "Поиск компьютера..."
                        )
                    }
                }
            },
            colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                focusedTextColor = Color.White,
                unfocusedTextColor = Color.White,
                disabledTextColor = Color.White,
                focusedBorderColor = Color.White,
                unfocusedBorderColor = Color(0xFF666666),
                disabledBorderColor = Color(0xFF444444),
                focusedLabelColor = Color.White,
                unfocusedLabelColor = Color(0xFFAAAAAA),
                disabledLabelColor = Color(0xFF888888),
                cursorColor = Color.White
            )
        )

        Spacer(Modifier.height(6.dp))

        Button(
            onClick = {
                if (connected) {
                    onDisconnect()
                } else {
                    onConnect()
                }
            },
            enabled = connected ||
                    (pcId.trim().isNotEmpty() && !connecting),
            modifier = Modifier
                .fillMaxWidth()
                .height(46.dp),
            colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                containerColor = if (connected) Color(0xFF8B1E1E) else Color(0xFF2C2C2C),
                disabledContainerColor = Color(0xFF202020)
            )
        ) {
            Text(
                text = when {
                    connected -> "ОТКЛЮЧИТЬСЯ"
                    connecting -> "ПОИСК КОМПЬЮТЕРА..."
                    else -> "ПОДКЛЮЧИТЬСЯ"
                },
                color = Color.White
            )
        }
    }
}

@Composable
private fun SessionControl(
    connecting: Boolean,
    connected: Boolean,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(52.dp)
            .background(Color.Black),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically
    ) {
        val label =
            when {
                connected -> "● ОТКЛЮЧИТЬ"
                connecting -> "● ПОДКЛЮЧЕНИЕ..."
                else -> "○ ПОДКЛЮЧИТЬ"
            }

        Button(
            onClick = {
                if (connected || connecting) {
                    if (connected) onDisconnect()
                } else {
                    onConnect()
                }
            },
            enabled = !connecting,
            contentPadding = PaddingValues(
                horizontal = 20.dp,
                vertical = 0.dp
            ),
            colors = androidx.compose.material3.ButtonDefaults.buttonColors(
                containerColor =
                    if (connected) Color(0xFF8B1E1E)
                    else Color(0xFF2C2C2C),
                disabledContainerColor = Color(0xFF2C2C2C)
            )
        ) {
            Text(
                text = label,
                color = Color.White
            )
        }
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
