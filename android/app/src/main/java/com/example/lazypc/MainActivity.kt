package com.example.lazypc

import android.os.Bundle
import android.content.ComponentName
import android.content.ServiceConnection
import android.os.IBinder
import android.util.Log
import android.os.Handler
import android.os.Looper
import android.content.Intent
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.content.ContextCompat
import com.example.lazypc.input.mouse.CursorState
import com.example.lazypc.input.mouse.MouseEmitter
import com.example.lazypc.input.PointerInputRouter
import com.example.lazypc.input.events.GestureEvent
import com.example.lazypc.input.gesture.ClientGestureEngine
import com.example.lazypc.input.keyboard.core.ActionResolver
import com.example.lazypc.input.keyboard.core.KeyboardEngine
import com.example.lazypc.input.keyboard.emit.KeyboardEmitter
import com.example.lazypc.input.keyboard.mapping.LanguageEN
import com.example.lazypc.ui.screens.RootScreen
import com.example.lazypc.video.CustomVideoRenderer
import com.example.lazypc.service.WebRTCForegroundService
import org.webrtc.VideoFrame
import org.webrtc.VideoSink
import org.webrtc.VideoTrack

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG_APP = "APP"
        private const val TAG_WS = "WS"
        private const val TAG_INPUT = "INPUT"

        private const val SIGNALING_URL =
            "ws://192.168.0.148:8000/ws"
    }

    private var webRtcService: WebRTCForegroundService? = null
    private var serviceBound = false

    private lateinit var renderer: CustomVideoRenderer

    private var currentVideoTrack: VideoTrack? = null

    private var detectedVideoWidth by mutableIntStateOf(0)
    private var detectedVideoHeight by mutableIntStateOf(0)

    private var lastVideoWidth = 0
    private var lastVideoHeight = 0

    private val videoSizeSink = object : VideoSink {
        override fun onFrame(frame: VideoFrame) {
            val width = frame.rotatedWidth
            val height = frame.rotatedHeight

            if (width <= 0 || height <= 0) return

            if (
                width == lastVideoWidth &&
                height == lastVideoHeight
            ) {
                return
            }

            lastVideoWidth = width
            lastVideoHeight = height

            Log.d(
                TAG_APP,
                "🎬 VIDEO SIZE: ${width}x${height}"
            )

            runOnUiThread {
                detectedVideoWidth = width
                detectedVideoHeight = height
            }
        }
    }

    private lateinit var mouseEmitter: MouseEmitter
    private lateinit var gestureEngine: ClientGestureEngine
    private lateinit var pointerInputRouter: PointerInputRouter

    private val cursorState =
        CursorState()

    private var mouseAreaWidth = 0f
    private var mouseAreaHeight = 0f

    private var videoAreaWidth = 0f
    private var videoAreaHeight = 0f

    // Valid mouse coordinates in fitted-video space.
    // At 1x these are the whole video; while zoomed they are the
    // currently visible source rectangle.
    private var mouseActionMinX = 0f
    private var mouseActionMaxX = Float.POSITIVE_INFINITY
    private var mouseActionMinY = 0f
    private var mouseActionMaxY = Float.POSITIVE_INFINITY

    private lateinit var keyboardEngine: KeyboardEngine
    private lateinit var keyboardEmitter: KeyboardEmitter

    private var dragModeEnabled = false

    private var sessionConnecting by mutableStateOf(false)
    private var sessionConnected by mutableStateOf(false)

    private val lifecycleHandler = Handler(Looper.getMainLooper())
    private var recoveryScheduled = false
    private var recoveryInProgress = false
    private var finishing = false
    private var sessionStarted = false

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(
            name: ComponentName?,
            service: IBinder?
        ) {
            val binder = service as? WebRTCForegroundService.LocalBinder
                ?: return

            webRtcService = binder.service()
            serviceBound = true

            Log.d(TAG_APP, "🟢 WEBRTC SERVICE BOUND")
            initializeFromService()
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            serviceBound = false
            webRtcService = null
            Log.w(TAG_APP, "🔴 WEBRTC SERVICE DISCONNECTED")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        WindowCompat.setDecorFitsSystemWindows(
            window,
            false
        )

        WindowInsetsControllerCompat(
            window,
            window.decorView
        ).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat
                    .BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }

        Log.d(TAG_APP, "🚀 LAZYPC START")

        val serviceIntent =
            Intent(this, WebRTCForegroundService::class.java)

        ContextCompat.startForegroundService(
            this,
            serviceIntent
        )

        bindService(
            serviceIntent,
            serviceConnection,
            BIND_AUTO_CREATE
        )
    }

    private fun initializeFromService() {
        val service = webRtcService ?: return

        val eglContext = service.eglContext()
        val webrtc = service.webRtcClient()

        mouseEmitter = MouseEmitter(webrtc)

        gestureEngine =
            ClientGestureEngine(
                isDragModeEnabled = {
                    dragModeEnabled
                },

                emit = { event ->
                    when (event) {
                        is GestureEvent.Move -> {
                            val targetX =
                                (cursorState.x + event.dx).coerceIn(
                                    mouseActionMinX,
                                    mouseActionMaxX
                                )

                            val targetY =
                                (cursorState.y + event.dy).coerceIn(
                                    mouseActionMinY,
                                    mouseActionMaxY
                                )

                            val actualDx = targetX - cursorState.x
                            val actualDy = targetY - cursorState.y

                            if (actualDx != 0f || actualDy != 0f) {
                                mouseEmitter.sendMove(
                                    actualDx,
                                    actualDy
                                )

                                cursorState.move(
                                    dx = actualDx,
                                    dy = actualDy,
                                    width = videoAreaWidth,
                                    height = videoAreaHeight
                                )
                            }
                        }

                        GestureEvent.Tap -> {
                            mouseEmitter.sendTap()
                        }

                        GestureEvent.DoubleTap -> {
                            mouseEmitter.sendDoubleTap()
                        }

                        GestureEvent.ContextMenu -> {
                            mouseEmitter.sendRightClick()
                        }

                        GestureEvent.DragStart -> {
                            mouseEmitter.sendDragStart()
                        }

                        is GestureEvent.DragMove -> {
                            val targetX =
                                (cursorState.x + event.dx).coerceIn(
                                    mouseActionMinX,
                                    mouseActionMaxX
                                )

                            val targetY =
                                (cursorState.y + event.dy).coerceIn(
                                    mouseActionMinY,
                                    mouseActionMaxY
                                )

                            val actualDx = targetX - cursorState.x
                            val actualDy = targetY - cursorState.y

                            if (actualDx != 0f || actualDy != 0f) {
                                mouseEmitter.sendDragMove(
                                    actualDx,
                                    actualDy
                                )

                                cursorState.move(
                                    dx = actualDx,
                                    dy = actualDy,
                                    width = videoAreaWidth,
                                    height = videoAreaHeight
                                )
                            }
                        }

                        GestureEvent.DragEnd -> {
                            mouseEmitter.sendDragEnd()
                        }

                        is GestureEvent.Scroll -> {
                            mouseEmitter.sendScroll(event.dy)
                        }
                    }
                }
            )

        pointerInputRouter =
            PointerInputRouter(gestureEngine)

        Log.d(TAG_INPUT, "✅ Mouse initialized")

        keyboardEngine =
            KeyboardEngine(
                resolver = ActionResolver(),
                language = LanguageEN()
            )

        keyboardEmitter = KeyboardEmitter(webrtc)

        setContent {
            RootScreen(
                eglContext = eglContext,

                videoWidth = detectedVideoWidth,
                videoHeight = detectedVideoHeight,

                onSurfaceCreated = { surface ->
                    if (::renderer.isInitialized) {
                        currentVideoTrack
                            ?.removeSink(renderer)
                    }

                    renderer = surface

                    currentVideoTrack
                        ?.addSink(renderer)

                    currentVideoTrack
                        ?.addSink(videoSizeSink)
                },

                onTouch = { event ->
                    pointerInputRouter.onTouch(event)
                },

                cursorState = cursorState,

                onMouseAreaSizeChanged = {
                        width,
                        height ->
                    mouseAreaWidth = width
                    mouseAreaHeight = height
                },

                onVideoAreaSizeChanged = {
                        width,
                        height ->
                    videoAreaWidth = width
                    videoAreaHeight = height

                    mouseActionMinX = 0f
                    mouseActionMaxX = width
                    mouseActionMinY = 0f
                    mouseActionMaxY = height

                    cursorState.initialize(
                        width,
                        height
                    )
                },

                onRecenterMouse = { targetX, targetY ->
                    val dx = targetX - cursorState.x
                    val dy = targetY - cursorState.y

                    if (dx != 0f || dy != 0f) {
                        mouseEmitter.sendMove(dx, dy)

                        cursorState.move(
                            dx = dx,
                            dy = dy,
                            width = videoAreaWidth,
                            height = videoAreaHeight
                        )
                    }
                },

                onMouseActionBoundsChanged = {
                        minX,
                        maxX,
                        minY,
                        maxY ->
                    mouseActionMinX = minX
                    mouseActionMaxX = maxX
                    mouseActionMinY = minY
                    mouseActionMaxY = maxY
                },

                keyboardEngine = keyboardEngine,
                keyboardEmitter = keyboardEmitter,

                onDragModeChanged = { enabled ->
                    dragModeEnabled = enabled

                    Log.d(
                        TAG_INPUT,
                        "🧲 Drag mode = $enabled"
                    )
                },

                sessionConnecting = sessionConnecting,
                sessionConnected = sessionConnected,

                onConnectSession = {
                    webRtcService?.connectSession()
                },

                onDisconnectSession = {
                    webRtcService?.disconnectSession()
                }
            )
        }

        service.registerUiCallbacks(
            onVideoTrackChanged = { track ->
                runOnUiThread {
                    if (currentVideoTrack === track) {
                        return@runOnUiThread
                    }

                    if (::renderer.isInitialized) {
                        currentVideoTrack
                            ?.removeSink(renderer)
                    }

                    currentVideoTrack
                        ?.removeSink(videoSizeSink)

                    currentVideoTrack = track

                    track?.addSink(videoSizeSink)

                    if (::renderer.isInitialized) {
                        track?.addSink(renderer)
                    }
                }
            },

            onCursorPosition = { normalizedX, normalizedY ->
                runOnUiThread {
                    cursorState.setNormalizedPosition(
                        normalizedX = normalizedX,
                        normalizedY = normalizedY,
                        width = videoAreaWidth,
                        height = videoAreaHeight
                    )
                }
            },

            onSignalingState = { connected ->
                Log.d(
                    TAG_WS,
                    if (connected) {
                        "🟢 SIGNALING CONNECTED [SERVICE]"
                    } else {
                        "🔴 SIGNALING DISCONNECTED [SERVICE]"
                    }
                )
            },

            onSessionState = { connecting, connected ->
                sessionConnecting = connecting
                sessionConnected = connected
            }
        )
    }

    override fun onPause() {
        super.onPause()
        Log.d(TAG_APP, "⏸ APP PAUSED")
        // Do not close WebRTC or force a signaling reconnect here.
        // If the OS/network keeps the transport alive, onResume will reuse it.
    }

    override fun onResume() {
        super.onResume()
        Log.d(TAG_APP, "▶ APP RESUMED")

        if (::renderer.isInitialized) {
            currentVideoTrack?.addSink(renderer)
        }

        currentVideoTrack?.addSink(videoSizeSink)
    }

    override fun onDestroy() {
        finishing = true
        lifecycleHandler.removeCallbacksAndMessages(null)

        if (serviceBound) {
            webRtcService?.unregisterUiCallbacks()
            unbindService(serviceConnection)
            serviceBound = false
        }

        if (::renderer.isInitialized) {
            currentVideoTrack?.removeSink(renderer)
            renderer.releaseRenderer()
        }

        currentVideoTrack?.removeSink(videoSizeSink)
        currentVideoTrack = null

        // Do NOT close WebRTC, signaling, or the foreground service here.
        // Those objects belong to the service and must survive Activity
        // recreation/backgrounding.

        super.onDestroy()
    }
}