package com.example.lazypc.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.cancel
import android.util.Log
import androidx.core.app.NotificationCompat
import com.example.lazypc.R
import com.example.lazypc.network.WsClient
import com.example.lazypc.webrtc.WebRTCClient
import org.json.JSONObject
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.VideoTrack

/**
 * Owns the long-lived LazyPC connection.
 *
 * Activity is UI only:
 * - creates/destroys TextureView/Compose UI;
 * - attaches the current VideoTrack to the renderer;
 * - sends user input through the WebRTCClient exposed by this service.
 *
 * The service owns:
 * - EglBase / WebRTCClient;
 * - PeerConnection;
 * - signaling WebSocket.
 *
 * This is intentionally the first clean service step. Recovery policy is
 * kept separate so a lifecycle migration cannot hide a reconnect bug.
 */
class WebRTCForegroundService : Service() {

    companion object {
        private const val TAG = "WEBRTC_SERVICE"
        private const val CHANNEL_ID = "lazypc_webrtc"
        private const val NOTIFICATION_ID = 1001
        private const val SIGNALING_URL =
            "ws://192.168.0.148:8000/ws"
    }

    private val binder = LocalBinder()

    private lateinit var eglBase: EglBase
    private lateinit var webrtc: WebRTCClient
    private lateinit var ws: WsClient

    private var currentVideoTrack: VideoTrack? = null
    private var currentCursorX = 0f
    private var currentCursorY = 0f

    private var onVideoTrackChanged: ((VideoTrack?) -> Unit)? = null
    private var onCursorPosition: ((Float, Float) -> Unit)? = null
    private var onSignalingState: ((Boolean) -> Unit)? = null
    private var onSessionState: ((Boolean, Boolean) -> Unit)? = null

    private var sessionConnecting = false
    private var sessionConnected = false
    private var sessionGeneration = 0L

    private val serviceScope =
        CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    override fun onCreate() {
        super.onCreate()

        createNotificationChannel()
        startForeground(
            NOTIFICATION_ID,
            buildNotification()
        )

        Log.d(TAG, "🚀 Foreground WebRTC service created")

        eglBase = EglBase.create()

        ws = WsClient(SIGNALING_URL)

        ws.setOnConnectionState { connected ->
            Log.d(
                "WS",
                if (connected) {
                    "🟢 SIGNALING CONNECTED [SERVICE]"
                } else {
                    "🔴 SIGNALING DISCONNECTED [SERVICE]"
                }
            )

            onSignalingState?.invoke(connected)
        }

        ws.setOnTextMessage { text ->
            handleSignalingMessage(text)
        }

        webrtc = WebRTCClient(
            context = this,
            eglContext = eglBase.eglBaseContext,

            onFrame = { track ->
                currentVideoTrack = track
                sessionConnecting = false
                sessionConnected = true
                onSessionState?.invoke(false, true)

                Log.d(TAG, "🎬 VIDEO TRACK UPDATED [SERVICE]")
                onVideoTrackChanged?.invoke(track)
            },

            onIce = { candidate ->
                val json = JSONObject().apply {
                    put("type", "candidate")
                    put("candidate", candidate.sdp)
                    put("sdpMid", candidate.sdpMid)
                    put("sdpMLineIndex", candidate.sdpMLineIndex)
                }

                ws.sendText(json.toString())
            },

            onCursorPosition = { normalizedX, normalizedY ->
                currentCursorX = normalizedX
                currentCursorY = normalizedY
                onCursorPosition?.invoke(
                    normalizedX,
                    normalizedY
                )
            }
        )

        webrtc.init()
        webrtc.createPeerConnection()

        // IMPORTANT:
        // Do not connect signaling automatically.
        // The user starts a real session from the UI button.
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int
    ): Int {
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder {
        return binder
    }

    fun registerUiCallbacks(
        onVideoTrackChanged: (VideoTrack?) -> Unit,
        onCursorPosition: (Float, Float) -> Unit,
        onSignalingState: (Boolean) -> Unit,
        onSessionState: (Boolean, Boolean) -> Unit
    ) {
        this.onVideoTrackChanged = onVideoTrackChanged
        this.onCursorPosition = onCursorPosition
        this.onSignalingState = onSignalingState
        this.onSessionState = onSessionState

        onVideoTrackChanged(currentVideoTrack)
        onCursorPosition(currentCursorX, currentCursorY)
        onSignalingState(ws.isConnected())
        onSessionState(sessionConnecting, sessionConnected)
    }

    fun unregisterUiCallbacks() {
        onVideoTrackChanged = null
        onCursorPosition = null
        onSignalingState = null
        onSessionState = null
    }

    fun connectSession() {
        if (sessionConnecting || sessionConnected) return

        sessionGeneration++
        sessionConnecting = true
        sessionConnected = false
        onSessionState?.invoke(sessionConnecting, sessionConnected)

        Log.d(TAG, "▶ Starting LazyPC session")

        ws.connect()
    }

    fun disconnectSession() {
        if (!sessionConnecting && !sessionConnected && !ws.isConnected()) {
            return
        }

        Log.d(TAG, "⏹ User requested session disconnect")

        val generationAtDisconnect = sessionGeneration

        sessionConnecting = false
        sessionConnected = false
        onSessionState?.invoke(false, false)

        // SESSION_CLOSE is the explicit, intentional-close signal.
        // Windows can distinguish this from a network disappearance.
        val sent = webrtc.sendText("SESSION_CLOSE")
        Log.d(TAG, "SESSION_CLOSE sent=$sent")

        serviceScope.launch {
            // Give SCTP a short window to put SESSION_CLOSE on the wire.
            if (sent) {
                delay(200)
            }

            // The user may have pressed CONNECT again during the short
            // graceful-close window. Never tear down the new session.
            if (generationAtDisconnect != sessionGeneration) {
                return@launch
            }

            currentVideoTrack = null
            onVideoTrackChanged?.invoke(null)

            // Keep the WebRTC factory alive, but replace only this session's
            // PeerConnection so the next CONNECT can negotiate a new session.
            webrtc.resetPeerConnection()

            // Signaling is no longer needed after P2P negotiation/session
            // teardown. It will be opened again by the next CONNECT.
            ws.close()
        }
    }

    fun eglContext(): EglBase.Context {
        return eglBase.eglBaseContext
    }

    fun webRtcClient(): WebRTCClient {
        return webrtc
    }

    fun isConnectionHealthy(): Boolean {
        return webrtc.isConnectionHealthy()
    }

    fun isConnectionDead(): Boolean {
        return webrtc.isConnectionDead()
    }

    fun resetPeerConnection() {
        currentVideoTrack = null
        onVideoTrackChanged?.invoke(null)
        webrtc.resetPeerConnection()
    }

    fun reconnectSignaling() {
        ws.reconnectNow()
    }

    private fun handleSignalingMessage(text: String) {
        if (!text.startsWith("{")) return

        try {
            val json = JSONObject(text)

            when (json.optString("type")) {
                "offer" -> {
                    val sdp = json.optString("sdp")
                    if (sdp.isEmpty()) return

                    Log.d(TAG, "📥 OFFER [SERVICE]")

                    webrtc.setRemoteOffer(sdp) { answer ->
                        ws.sendAnswer(answer)
                    }
                }

                "candidate" -> {
                    val candidateSdp =
                        json.optString("candidate")

                    if (candidateSdp.isEmpty()) return

                    val candidate = IceCandidate(
                        json.optString("sdpMid"),
                        json.optInt("sdpMLineIndex"),
                        candidateSdp
                    )

                    webrtc.addRemoteCandidate(candidate)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "SIGNALING ERROR [SERVICE]", e)
        }
    }

    private fun buildNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle("LazyPC")
            .setContentText("Remote connection is active")
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

        val channel = NotificationChannel(
            CHANNEL_ID,
            "LazyPC connection",
            NotificationManager.IMPORTANCE_LOW
        ).apply {
            description =
                "Keeps the LazyPC remote connection active in background"
            setShowBadge(false)
        }

        getSystemService(
            NotificationManager::class.java
        ).createNotificationChannel(channel)
    }

    override fun onDestroy() {
        Log.w(TAG, "🛑 Foreground WebRTC service destroyed")

        onVideoTrackChanged = null
        onCursorPosition = null
        onSignalingState = null

        serviceScope.cancel()

        if (::ws.isInitialized) {
            ws.close()
        }

        if (::webrtc.isInitialized) {
            webrtc.close()
        }

        if (::eglBase.isInitialized) {
            eglBase.release()
        }

        super.onDestroy()
    }

    inner class LocalBinder : Binder() {
        fun service(): WebRTCForegroundService = this@WebRTCForegroundService
    }
}