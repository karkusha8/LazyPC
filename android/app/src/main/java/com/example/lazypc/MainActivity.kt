package com.example.lazypc

import android.os.Bundle
import android.util.Log
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import com.example.lazypc.input.CursorState
import com.example.lazypc.input.MouseEmitter
import com.example.lazypc.input.PointerInputRouter
import com.example.lazypc.input.events.GestureEvent
import com.example.lazypc.input.gesture.ClientGestureEngine
import com.example.lazypc.keyboard.core.ActionResolver
import com.example.lazypc.keyboard.core.KeyboardEngine
import com.example.lazypc.keyboard.emit.KeyboardEmitter
import com.example.lazypc.keyboard.mapping.LanguageEN
import com.example.lazypc.network.WsClient
import com.example.lazypc.ui.screens.RootScreen
import com.example.lazypc.webrtc.WebRTCClient
import org.json.JSONObject
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.SurfaceViewRenderer
import org.webrtc.VideoTrack
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat


class MainActivity : AppCompatActivity() {

    companion object {

        private const val TAG_APP = "APP"
        private const val TAG_WS = "WS"
        private const val TAG_INPUT = "INPUT"

        private const val SIGNALING_URL =
            "ws://192.168.0.148:8000/ws"
    }


    private lateinit var ws: WsClient

    private lateinit var webrtc: WebRTCClient

    private lateinit var renderer: SurfaceViewRenderer

    private lateinit var eglBase: EglBase

    private var currentVideoTrack: VideoTrack? = null


    private lateinit var mouseEmitter: MouseEmitter

    private lateinit var gestureEngine: ClientGestureEngine

    private lateinit var pointerInputRouter: PointerInputRouter


    private val cursorState =
        CursorState()


    /*
     * ================================================================
     * TOUCH AREA
     *
     * Область, на которой пользователь управляет мышью.
     * ================================================================
     */


    private var mouseAreaWidth =
        0f


    private var mouseAreaHeight =
        0f


    /*
     * ================================================================
     * VIDEO AREA
     *
     * Область, внутри которой рисуется курсор Windows.
     * ================================================================
     */


    private var videoAreaWidth =
        0f


    private var videoAreaHeight =
        0f


    private lateinit var keyboardEngine:
            KeyboardEngine


    private lateinit var keyboardEmitter:
            KeyboardEmitter


    private var dragModeEnabled =
        false


    override fun onCreate(
        savedInstanceState: Bundle?
    ) {

        super.onCreate(savedInstanceState)


        // ============================================================
        // ANDROID IMMERSIVE MODE
        // ============================================================

        WindowCompat.setDecorFitsSystemWindows(
            window,
            false
        )


        WindowInsetsControllerCompat(
            window,
            window.decorView
        ).apply {

            hide(
                WindowInsetsCompat.Type.systemBars()
            )


            systemBarsBehavior =

                WindowInsetsControllerCompat
                    .BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }


        Log.d(
            TAG_APP,
            "🚀 LAZYPC START"
        )


        eglBase =
            EglBase.create()


        // ============================================================
        // WEBRTC
        // ============================================================


        webrtc =

            WebRTCClient(

                context = this,

                eglContext =
                    eglBase.eglBaseContext,


                onFrame = { track ->

                    runOnUiThread {

                        if (
                            currentVideoTrack === track
                        ) {

                            return@runOnUiThread
                        }


                        if (
                            ::renderer.isInitialized
                        ) {

                            currentVideoTrack
                                ?.removeSink(renderer)
                        }


                        currentVideoTrack =
                            track


                        if (
                            !::renderer.isInitialized
                        ) {

                            return@runOnUiThread
                        }


                        track.addSink(renderer)
                    }
                },


                onIce = { candidate ->

                    if (
                        !::ws.isInitialized
                    ) {

                        return@WebRTCClient
                    }


                    val json =

                        JSONObject().apply {

                            put(
                                "type",
                                "candidate"
                            )

                            put(
                                "candidate",
                                candidate.sdp
                            )

                            put(
                                "sdpMid",
                                candidate.sdpMid
                            )

                            put(
                                "sdpMLineIndex",
                                candidate.sdpMLineIndex
                            )
                        }


                    ws.sendText(
                        json.toString()
                    )
                },


                onCursorPosition = {

                        normalizedX,
                        normalizedY ->


                    runOnUiThread {

                        /*
                         * Windows присылает:
                         *
                         * X = 0.0 .. 1.0
                         * Y = 0.0 .. 1.0
                         *
                         * Переводим координаты именно
                         * в размеры VIDEO AREA.
                         */


                        cursorState
                            .setNormalizedPosition(

                                normalizedX =
                                    normalizedX,

                                normalizedY =
                                    normalizedY,

                                width =
                                    videoAreaWidth,

                                height =
                                    videoAreaHeight
                            )
                    }
                }
            )


        webrtc.init()

        webrtc.createPeerConnection()


        // ============================================================
        // MOUSE
        // ============================================================


        mouseEmitter =
            MouseEmitter(webrtc)


        gestureEngine =

            ClientGestureEngine(

                isDragModeEnabled = {

                    dragModeEnabled
                },


                emit = { event ->

                    when (event) {


                        is GestureEvent.Move -> {

                            mouseEmitter.sendMove(
                                event.dx,
                                event.dy
                            )


                            /*
                             * Локальный курсор также двигается
                             * в координатах VIDEO AREA.
                             */


                            cursorState.move(

                                dx =
                                    event.dx,

                                dy =
                                    event.dy,

                                width =
                                    videoAreaWidth,

                                height =
                                    videoAreaHeight
                            )
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

                            mouseEmitter.sendDragMove(
                                event.dx,
                                event.dy
                            )


                            cursorState.move(

                                dx =
                                    event.dx,

                                dy =
                                    event.dy,

                                width =
                                    videoAreaWidth,

                                height =
                                    videoAreaHeight
                            )
                        }


                        GestureEvent.DragEnd -> {

                            mouseEmitter.sendDragEnd()
                        }


                        is GestureEvent.Scroll -> {

                            mouseEmitter.sendScroll(
                                event.dy
                            )
                        }
                    }
                }
            )


        pointerInputRouter =

            PointerInputRouter(
                gestureEngine
            )


        Log.d(
            TAG_INPUT,
            "✅ Mouse initialized"
        )


        // ============================================================
        // KEYBOARD
        // ============================================================


        keyboardEngine =

            KeyboardEngine(

                resolver =
                    ActionResolver(),

                language =
                    LanguageEN()
            )


        keyboardEmitter =

            KeyboardEmitter(
                webrtc
            )


        // ============================================================
        // UI
        // ============================================================


        setContent {


            RootScreen(

                eglContext =
                    eglBase.eglBaseContext,


                onSurfaceCreated = { surface ->


                    if (::renderer.isInitialized) {

                        currentVideoTrack
                            ?.removeSink(renderer)

                    }


                    renderer =
                        surface


                    currentVideoTrack
                        ?.addSink(renderer)
                },


                onTouch = { event ->

                    pointerInputRouter.onTouch(
                        event
                    )
                },


                cursorState =
                    cursorState,


                /*
                 * TOUCH AREA SIZE
                 */


                onMouseAreaSizeChanged = {
                        width,
                        height ->


                    mouseAreaWidth =
                        width


                    mouseAreaHeight =
                        height
                },


                /*
                 * VIDEO AREA SIZE
                 */


                onVideoAreaSizeChanged = {
                        width,
                        height ->


                    videoAreaWidth =
                        width


                    videoAreaHeight =
                        height


                    cursorState.initialize(
                        width,
                        height
                    )
                },


                keyboardEngine =
                    keyboardEngine,


                keyboardEmitter =
                    keyboardEmitter,


                onDragModeChanged = { enabled ->

                    dragModeEnabled =
                        enabled


                    Log.d(
                        TAG_INPUT,
                        "🧲 Drag mode = $enabled"
                    )
                }
            )
        }


        // ============================================================
        // SIGNALING
        // ============================================================


        ws =
            WsClient(
                SIGNALING_URL
            )


        ws.setOnTextMessage { text ->

            if (
                !text.startsWith("{")
            ) {

                return@setOnTextMessage
            }


            try {

                val json =
                    JSONObject(text)


                when (
                    json.optString("type")
                ) {


                    "offer" -> {

                        val sdp =
                            json.optString("sdp")


                        if (
                            sdp.isEmpty()
                        ) {

                            return@setOnTextMessage
                        }


                        webrtc.setRemoteOffer(
                            sdp
                        ) { answer ->

                            ws.sendAnswer(answer)
                        }
                    }


                    "candidate" -> {

                        val candidateSdp =
                            json.optString(
                                "candidate"
                            )


                        if (
                            candidateSdp.isEmpty()
                        ) {

                            return@setOnTextMessage
                        }


                        val candidate =

                            IceCandidate(

                                json.optString(
                                    "sdpMid"
                                ),

                                json.optInt(
                                    "sdpMLineIndex"
                                ),

                                candidateSdp
                            )


                        webrtc.addRemoteCandidate(
                            candidate
                        )
                    }
                }


            } catch (
                e: Exception
            ) {

                Log.e(
                    TAG_WS,
                    "SIGNALING ERROR",
                    e
                )
            }
        }


        ws.connect()
    }
    override fun onPause() {

        super.onPause()


        Log.d(
            TAG_APP,
            "⏸ APP PAUSED"
        )
    }



    override fun onResume() {

        super.onResume()


        Log.d(
            TAG_APP,
            "▶ APP RESUMED"


        )


        if (::renderer.isInitialized) {

            currentVideoTrack
                ?.addSink(renderer)

        }
    }

    override fun onDestroy() {


        if (::renderer.isInitialized) {


            currentVideoTrack
                ?.removeSink(renderer)


            renderer.release()

        }



        currentVideoTrack = null



        super.onDestroy()
    }
}