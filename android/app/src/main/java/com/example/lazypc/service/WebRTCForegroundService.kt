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
import kotlinx.coroutines.Job
import org.json.JSONObject
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.VideoTrack

class WebRTCForegroundService : Service() {

    companion object {
        private const val TAG = "WEBRTC_SERVICE"
        private const val CHANNEL_ID = "lazypc_webrtc"
        private const val NOTIFICATION_ID = 1001
        private const val SESSION_TIMEOUT_MS = 30_000L

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
    private var onTrustedPcPaired: ((String) -> Unit)? = null
    private var onDirectSessionState: ((Boolean, Boolean, String?) -> Unit)? = null

    private var sessionConnecting = false
    private var sessionConnected = false
    private var sessionGeneration = 0L
    private var sessionTimeoutJob: Job? = null
    private var directSessionTimeoutJob: Job? = null

    /*
     * Existing Trusted Device pairing state.
     *
     * Completely separate from direct PC selection.
     */
    private var pendingPairingPayload: String? = null

    /*
     * ---------------------------------------------------------------------
     * NEW SIMPLIFIED CONNECTION MODEL
     * ---------------------------------------------------------------------
     *
     * Android asks the signaling server to locate a concrete PC by ID.
     *
     * This state has nothing to do with Trusted Device pairing.
     */
    private var pendingPcId: String? = null

    // Already-paired Trusted PC selected by the user.
    private var pendingTrustedPcCode: String? = null
    private var trustedAttemptActive = false

    private var directAttemptActive = false
    private var directConnected = false
    private var directError: String? = null

    private val serviceScope =
        CoroutineScope(
            SupervisorJob() +
                    Dispatchers.Main.immediate
        )

    override fun onCreate() {
        super.onCreate()

        createNotificationChannel()

        startForeground(
            NOTIFICATION_ID,
            buildNotification()
        )

        Log.d(
            TAG,
            "🚀 Foreground WebRTC service created"
        )

        eglBase = EglBase.create()

        ws = WsClient(
            context = this,
            url = SIGNALING_URL
        )

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

            if (!connected && sessionConnecting) {
                failPendingSession(
                    "Signaling disconnected"
                )

                return@setOnConnectionState
            }

            if (!connected && directAttemptActive) {
                failDirectConnection(
                    "Signaling disconnected"
                )

                return@setOnConnectionState
            }

            if (connected) {

                /*
                 * There are three mutually exclusive signaling flows:
                 *
                 * 1. QR Trusted Device enrollment
                 *    -> create_session + pairing_token
                 *
                 * 2. Normal Trusted Device connection
                 *    -> plain create_session
                 *
                 * 3. Direct PC-ID connection
                 *    -> find_pc
                 *
                 * Keep the flows separate. In particular, do not send
                 * a normal create_session for a QR pairing attempt.
                 */
                val pairingPending =
                    pendingPairingPayload != null

                sendPendingPairingSession()

                /*
                 * NEW simplified direct-PC path.
                 *
                 * We only send find_pc after onOpen().
                 */
                sendPendingPcSelection()

                /*
                 * Trusted Device connection is now explicitly targeted.
                 * The selected PC must be known before create_session can
                 * be routed by signaling.
                 */
                if (!pairingPending) {
                    sendPendingTrustedPcSelection()
                }
            }
        }

        ws.setOnTextMessage { text ->
            handleSignalingMessage(text)
        }

        webrtc = WebRTCClient(
            context = this,
            eglContext = eglBase.eglBaseContext,

            onFrame = { track ->

                sessionTimeoutJob?.cancel()
                sessionTimeoutJob = null

                currentVideoTrack = track

                if (directAttemptActive) {
                    directSessionTimeoutJob?.cancel()
                    directSessionTimeoutJob = null
                    pendingPcId = null
                    directAttemptActive = false
                    directConnected = true
                    directError = null

                    onDirectSessionState?.invoke(
                        false,
                        true,
                        null
                    )

                    Log.d(
                        TAG,
                        "🟢 DIRECT PC CONNECTION ESTABLISHED"
                    )
                } else {
                    sessionTimeoutJob?.cancel()
                    sessionTimeoutJob = null

                    sessionConnecting = false
                    sessionConnected = true

                    onSessionState?.invoke(
                        false,
                        true
                    )
                }

                Log.d(
                    TAG,
                    "🎬 VIDEO TRACK UPDATED [SERVICE]"
                )

                onVideoTrackChanged?.invoke(track)
            },

            onIce = { candidate ->

                val json = JSONObject().apply {
                    put("type", "candidate")
                    put("candidate", candidate.sdp)
                    put("sdpMid", candidate.sdpMid)
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

        /*
         * IMPORTANT:
         *
         * Signaling is still NOT connected automatically.
         *
         * The user starts one of the connection models explicitly.
         */
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int
    ): Int {
        return START_STICKY
    }

    override fun onBind(
        intent: Intent?
    ): IBinder {
        return binder
    }

    fun registerUiCallbacks(
        onVideoTrackChanged:
            (VideoTrack?) -> Unit,

        onCursorPosition:
            (Float, Float) -> Unit,

        onSignalingState:
            (Boolean) -> Unit,

        onSessionState:
            (Boolean, Boolean) -> Unit
    ) {
        this.onVideoTrackChanged =
            onVideoTrackChanged

        this.onCursorPosition =
            onCursorPosition

        this.onSignalingState =
            onSignalingState

        this.onSessionState =
            onSessionState

        onVideoTrackChanged(
            currentVideoTrack
        )

        onCursorPosition(
            currentCursorX,
            currentCursorY
        )

        onSignalingState(
            ws.isConnected()
        )

        onSessionState(
            sessionConnecting,
            sessionConnected
        )
    }

    fun registerTrustedPcPairedCallback(
        callback: (String) -> Unit
    ) {
        onTrustedPcPaired = callback
    }

    fun registerDirectConnectionCallback(
        callback: (Boolean, Boolean, String?) -> Unit
    ) {
        onDirectSessionState = callback
        callback(
            directAttemptActive,
            directConnected,
            directError
        )
    }

    fun unregisterUiCallbacks() {
        onVideoTrackChanged = null
        onCursorPosition = null
        onSignalingState = null
        onSessionState = null
        onTrustedPcPaired = null
        onDirectSessionState = null
    }

    // =====================================================================
    // TRUSTED DEVICE CONNECTION
    // =====================================================================

    fun connectTrusted(pcCode: String) {
        val normalized = pcCode.filter { it.isDigit() }

        if (normalized.length != 9) {
            Log.e(TAG, "❌ Trusted connection rejected: PC code must be exactly 9 digits")
            return
        }

        if (sessionConnecting || sessionConnected || directAttemptActive) {
            Log.w(TAG, "Trusted connection requested while another session is active")
            return
        }

        if (pendingPairingPayload != null) {
            Log.w(TAG, "Trusted connection rejected: pairing is pending")
            return
        }

        pendingTrustedPcCode = normalized
        trustedAttemptActive = true
        sessionGeneration++
        sessionConnecting = true
        sessionConnected = false

        onSessionState?.invoke(true, false)
        startSessionTimeout(sessionGeneration)

        val formatted = "${normalized.substring(0, 3)} ${normalized.substring(3, 6)} ${normalized.substring(6, 9)}"
        Log.d(TAG, "▶ Connecting to Trusted PC: $formatted")

        if (ws.isOpen()) {
            sendPendingTrustedPcSelection()
        } else {
            ws.connect()
        }
    }

    private fun sendPendingTrustedPcSelection() {
        val pcCode = pendingTrustedPcCode ?: return
        if (!trustedAttemptActive || !ws.isOpen()) return

        val formatted = "${pcCode.substring(0, 3)} ${pcCode.substring(3, 6)} ${pcCode.substring(6, 9)}"
        val sent = ws.connectTrusted(pcCode)

        if (sent) {
            pendingTrustedPcCode = null
            Log.d(TAG, "🔐 connect_trusted sent: $formatted")
        } else {
            Log.e(TAG, "❌ Failed to send connect_trusted")
            failPendingSession("Failed to select Trusted PC")
        }
    }

    // =====================================================================
    // EXISTING CONNECTION MODEL
    // =====================================================================

    fun connectSession() {
        if (
            sessionConnecting ||
            sessionConnected
        ) {
            return
        }

        sessionGeneration++

        sessionConnecting = true
        sessionConnected = false

        onSessionState?.invoke(
            sessionConnecting,
            sessionConnected
        )

        startSessionTimeout(
            sessionGeneration
        )

        Log.d(
            TAG,
            "▶ Starting LazyPC session"
        )

        /*
         * If signaling is already OPEN, send create_session immediately.
         * Otherwise onConnectionState(true) will send it after onOpen().
         */
        if (ws.isOpen()) {
            sendNormalSession()
        } else {
            ws.connect()
        }
    }

    /**
     * Starts the normal Trusted Device session.
     *
     * This is intentionally different from QR pairing:
     *
     *   normal connection -> {"type":"create_session"}
     *   QR pairing       -> {"type":"create_session","pairing_token":...}
     *
     * The Agent will then perform the normal Trusted Device AUTH V3 flow.
     */
    private fun sendNormalSession() {
        if (!sessionConnecting) {
            return
        }

        if (pendingPairingPayload != null) {
            return
        }

        if (directAttemptActive) {
            return
        }

        if (!ws.isOpen()) {
            return
        }

        val sent =
            ws.sendJson(
                JSONObject().apply {
                    put(
                        "type",
                        "create_session"
                    )
                }
            )

        if (sent) {
            Log.d(
                TAG,
                "🔐 Trusted Device create_session sent"
            )
        } else {
            Log.e(
                TAG,
                "❌ Failed to send Trusted Device create_session"
            )

            failPendingSession(
                "Failed to send create_session"
            )
        }
    }

    // =====================================================================
    // NEW SIMPLIFIED CONNECTION MODEL
    // =====================================================================

    /**
     * Connect to a specific Windows PC by its persistent PC ID.
     *
     * This is deliberately separate from connectSession().
     *
     * Flow:
     *
     *   connectToPc()
     *        ↓
     *   WebSocket
     *        ↓
     *   HELLO_CLIENT
     *        ↓
     *   find_pc
     *        ↓
     *   pc_found
     *        ↓
     *   server -> Agent: create_session
     *        ↓
     *   Agent -> offer
     *        ↓
     *   existing WebRTC signaling
     */
    fun connectToPc(
        pcId: String
    ) {
        val normalizedPcId =
            pcId.trim()

        if (normalizedPcId.isBlank()) {
            Log.e(
                TAG,
                "❌ Direct connection rejected: empty PC ID"
            )
            return
        }

        val isPublicPcCode =
            normalizedPcId.length == 9 &&
                    normalizedPcId.all { it.isDigit() }

        if (!isPublicPcCode) {
            Log.e(
                TAG,
                "❌ Direct connection rejected: PC code must be exactly 9 digits"
            )
            return
        }

        val formattedPcCode =
            "${normalizedPcId.substring(0, 3)} " +
                    "${normalizedPcId.substring(3, 6)} " +
                    normalizedPcId.substring(6, 9)

        if (
            sessionConnecting ||
            sessionConnected
        ) {
            Log.w(
                TAG,
                "Direct connection requested while session is active"
            )
            return
        }

        /*
         * This model and Trusted Pairing must never be armed
         * at the same time.
         */
        if (pendingPairingPayload != null) {
            Log.w(
                TAG,
                "Direct connection rejected: Trusted pairing is pending"
            )
            return
        }

        pendingPcId = normalizedPcId
        directAttemptActive = true
        directConnected = false
        directError = null

        directSessionTimeoutJob?.cancel()
        directSessionTimeoutJob = serviceScope.launch {
            delay(SESSION_TIMEOUT_MS)
            if (directAttemptActive && !directConnected) {
                failDirectConnection("Connection timeout")
            }
        }

        onDirectSessionState?.invoke(
            true,
            false,
            null
        )

        Log.d(
            TAG,
            "▶ Connecting directly to PC: $formattedPcCode"
        )

        /*
         * If WebSocket is already fully OPEN, send find_pc now.
         *
         * If it is CONNECTING or completely closed, connect().
         *
         * We deliberately use isOpen(), not isConnected(),
         * because socket != null may still mean CONNECTING.
         */
        if (ws.isOpen()) {
            sendPendingPcSelection()
        } else {
            ws.connect()
        }
    }

    /**
     * Sends the pending find_pc request.
     *
     * This is called either:
     *
     *   - immediately if WebSocket is already OPEN;
     *   - from onConnectionState(true) after onOpen().
     */
    private fun failDirectConnection(reason: String) {
        Log.e(TAG, "❌ Direct PC connection failed: $reason")

        directSessionTimeoutJob?.cancel()
        directSessionTimeoutJob = null
        pendingPcId = null
        directAttemptActive = false
        directConnected = false
        directError = reason

        onDirectSessionState?.invoke(
            false,
            false,
            reason
        )

        try {
            webrtc.resetPeerConnection()
        } catch (error: Throwable) {
            Log.e(TAG, "Failed to reset WebRTC after direct connection failure", error)
        }

        if (ws.isConnected()) {
            ws.close()
        }
    }

    private fun sendPendingPcSelection() {
        val pcId =
            pendingPcId
                ?: return

        if (!ws.isOpen()) {
            return
        }

        /*
         * Do not send the request twice.
         */
        pendingPcId = null

        val sent =
            ws.findPc(pcId)

        if (!sent) {
            Log.e(
                TAG,
                "❌ Failed to send find_pc"
            )

            /*
             * Restore the pending ID only if the
             * session is still the same attempt.
             *
             * In practice send() should only fail if
             * the socket disappeared between isOpen()
             * and send().
             */
            pendingPcId = pcId

            failDirectConnection(
                "Failed to send find_pc"
            )

            return
        }

        Log.d(
            TAG,
            "📤 find_pc sent"
        )
    }

    // =====================================================================
    // EXISTING TRUSTED DEVICE PAIRING
    // =====================================================================

    /**
     * Starts a Trusted Device enrollment session from a QR payload.
     *
     * This is intentionally NOT the same as connectSession()
     * or connectToPc().
     */
    fun connectTrustedPairingSession(
        qrPayload: String
    ) {
        if (
            sessionConnecting ||
            sessionConnected
        ) {
            Log.w(
                TAG,
                "Trusted pairing requested while session is active"
            )
            return
        }

        if (qrPayload.isBlank()) {
            Log.e(
                TAG,
                "Trusted pairing rejected: empty QR payload"
            )
            return
        }

        if (pendingPcId != null) {
            Log.w(
                TAG,
                "Trusted pairing rejected: direct PC connection is pending"
            )
            return
        }

        sessionGeneration++

        sessionConnecting = true
        sessionConnected = false

        onSessionState?.invoke(
            true,
            false
        )

        startSessionTimeout(
            sessionGeneration
        )

        /*
         * Existing Trusted Pairing protocol.
         *
         * UNCHANGED.
         */
        webrtc.startTrustedPairing(
            qrPayload
        )

        pendingPairingPayload =
            qrPayload

        Log.d(
            TAG,
            "🔐 Starting Trusted Device pairing session"
        )

        if (ws.isOpen()) {
            sendPendingPairingSession()
        } else {
            ws.connect()
        }
    }

    private fun sendPendingPairingSession() {
        val payload =
            pendingPairingPayload
                ?: return

        if (!ws.isOpen()) {
            return
        }

        pendingPairingPayload = null

        try {
            ws.startTrustedPairingSession(
                payload
            )

            Log.d(
                TAG,
                "🔐 Trusted pairing create_session sent"
            )

        } catch (e: Exception) {

            Log.e(
                TAG,
                "❌ Failed to start Trusted Device pairing",
                e
            )

            sessionConnecting = false
            sessionConnected = false

            onSessionState?.invoke(
                false,
                false
            )
        }
    }

    // =====================================================================
    // SESSION TIMEOUT / FAILURE
    // =====================================================================

    private fun startSessionTimeout(
        generation: Long
    ) {
        sessionTimeoutJob?.cancel()

        sessionTimeoutJob =
            serviceScope.launch {

                delay(
                    SESSION_TIMEOUT_MS
                )

                if (
                    generation !=
                    sessionGeneration
                ) {
                    return@launch
                }

                if (
                    !sessionConnecting ||
                    sessionConnected
                ) {
                    return@launch
                }

                Log.e(
                    TAG,
                    "⏱ Session connection timeout"
                )

                failPendingSession(
                    "Connection timeout"
                )
            }
    }

    private fun failPendingSession(
        reason: String
    ) {
        if (!sessionConnecting) {
            return
        }

        Log.e(
            TAG,
            "❌ Session failed: $reason"
        )

        sessionTimeoutJob?.cancel()
        sessionTimeoutJob = null
        directSessionTimeoutJob?.cancel()
        directSessionTimeoutJob = null

        /*
         * Clear BOTH pending connection modes.
         *
         * They are mutually exclusive.
         */
        pendingPairingPayload = null
        pendingPcId = null

        sessionGeneration++

        sessionConnecting = false
        sessionConnected = false

        currentVideoTrack = null

        onVideoTrackChanged?.invoke(
            null
        )

        onSessionState?.invoke(
            false,
            false
        )

        try {
            webrtc.resetPeerConnection()

        } catch (error: Throwable) {

            Log.e(
                TAG,
                "Failed to reset WebRTC after session failure",
                error
            )
        }

        ws.close()
    }

    // =====================================================================
    // DISCONNECT
    // =====================================================================

    fun disconnectSession() {

        if (
            !sessionConnecting &&
            !sessionConnected &&
            !ws.isConnected()
        ) {
            return
        }

        Log.d(
            TAG,
            "⏹ User requested session disconnect"
        )

        pendingPairingPayload = null
        pendingPcId = null

        val generationAtDisconnect =
            sessionGeneration

        sessionTimeoutJob?.cancel()
        sessionTimeoutJob = null

        sessionConnecting = false
        sessionConnected = false

        onSessionState?.invoke(
            false,
            false
        )

        /*
         * Existing graceful close protocol.
         */
        val sent =
            webrtc.sendText(
                "SESSION_CLOSE"
            )

        Log.d(
            TAG,
            "SESSION_CLOSE sent=$sent"
        )

        serviceScope.launch {

            if (sent) {
                delay(200)
            }

            if (
                generationAtDisconnect !=
                sessionGeneration
            ) {
                return@launch
            }

            currentVideoTrack = null

            onVideoTrackChanged?.invoke(
                null
            )

            /*
             * Keep WebRTC factory alive.
             * Replace only the PeerConnection.
             */
            webrtc.resetPeerConnection()

            /*
             * Signaling is not needed anymore.
             * Next explicit connection opens it again.
             */
            ws.close()
        }
    }

    /**
     * Disconnects the current direct PC-code connection.
     *
     * This is intentionally separate from the legacy session disconnect
     * because direct PC-code connections use their own state machine.
     *
     * After this returns the same service can immediately accept another
     * connectToPc() attempt with the same or a different PC code.
     */
    fun disconnectToPc() {
        disconnectDirectPc()
    }

    private fun disconnectDirectPc() {
        directSessionTimeoutJob?.cancel()
        directSessionTimeoutJob = null
        pendingPcId = null
        directAttemptActive = false
        directConnected = false
        directError = null

        onDirectSessionState?.invoke(
            false,
            false,
            null
        )

        try {
            webrtc.sendText("SESSION_CLOSE")
            webrtc.resetPeerConnection()
        } catch (error: Throwable) {
            Log.e(TAG, "Failed to close direct PC session", error)
        }

        currentVideoTrack = null
        onVideoTrackChanged?.invoke(null)
        ws.close()
    }

    // =====================================================================
    // WEBRTC ACCESS
    // =====================================================================

    fun eglContext():
            EglBase.Context {
        return eglBase.eglBaseContext
    }

    fun webRtcClient():
            WebRTCClient {
        return webrtc
    }

    fun isConnectionHealthy():
            Boolean {
        return webrtc.isConnectionHealthy()
    }

    fun isConnectionDead():
            Boolean {
        return webrtc.isConnectionDead()
    }

    fun resetPeerConnection() {
        currentVideoTrack = null

        onVideoTrackChanged?.invoke(
            null
        )

        webrtc.resetPeerConnection()
    }

    fun reconnectSignaling() {
        ws.reconnectNow()
    }

    // =====================================================================
    // SIGNALING
    // =====================================================================

    private fun handleSignalingMessage(
        text: String
    ) {
        if (!text.startsWith("{")) {
            return
        }

        try {
            val json =
                JSONObject(text)

            when (
                json.optString("type")
            ) {

                "trusted_pc_selected" -> {
                    Log.d(
                        TAG,
                        "🔐 Trusted PC selected by signaling: " +
                                json.optString("pc_code")
                    )
                }

                "trusted_route_failed" -> {
                    val reason = json.optString("reason", "Unknown error")
                    Log.e(TAG, "❌ Trusted PC route failed: $reason")
                    trustedAttemptActive = false
                    pendingTrustedPcCode = null
                    failPendingSession("Trusted PC route failed: $reason")
                }

                "trusted_pairing_complete" -> {
                    val pcCode = json.optString("pc_code")
                    val normalized = pcCode.filter { it.isDigit() }
                    if (normalized.length == 9) {
                        Log.d(TAG, "✅ Trusted PC pairing completed: $normalized")
                        onTrustedPcPaired?.invoke(normalized)
                    }
                }

                /*
                 * ---------------------------------------------------------
                 * NEW DIRECT-PC MODEL
                 * ---------------------------------------------------------
                 */

                "pc_found" -> {

                    val pcId =
                        json.optString(
                            "pc_code"
                        ).ifBlank {
                            json.optString("pc_id")
                        }

                    val displayCode =
                        if (
                            pcId.length == 9 &&
                            pcId.all { it.isDigit() }
                        ) {
                            "${pcId.substring(0, 3)} " +
                                    "${pcId.substring(3, 6)} " +
                                    pcId.substring(6, 9)
                        } else {
                            pcId
                        }

                    Log.d(
                        TAG,
                        "🖥️ PC FOUND: $displayCode"
                    )

                    /*
                     * The server has now attached this client
                     * to the selected Agent.
                     *
                     * IMPORTANT:
                     *
                     * We do NOT send create_session here.
                     *
                     * The server already does:
                     *
                     * registry.send_create_session(pc_id)
                     */
                }

                "pc_not_found" -> {

                    val pcId =
                        json.optString(
                            "pc_code"
                        ).ifBlank {
                            json.optString("pc_id")
                        }

                    Log.e(
                        TAG,
                        "❌ PC NOT FOUND: $pcId"
                    )

                    failDirectConnection(
                        "PC not found"
                    )
                }

                /*
                 * ---------------------------------------------------------
                 * EXISTING WEBRTC SIGNALING
                 * ---------------------------------------------------------
                 */

                "offer" -> {

                    val sdp =
                        json.optString(
                            "sdp"
                        )

                    if (sdp.isEmpty()) {
                        return
                    }

                    Log.d(
                        TAG,
                        "📥 OFFER [SERVICE]"
                    )

                    webrtc.setRemoteOffer(
                        sdp
                    ) { answer ->

                        ws.sendAnswer(
                            answer
                        )
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
                        return
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

        } catch (e: Exception) {

            Log.e(
                TAG,
                "SIGNALING ERROR [SERVICE]",
                e
            )
        }
    }

    // =====================================================================
    // NOTIFICATION
    // =====================================================================

    private fun buildNotification():
            Notification {

        return NotificationCompat.Builder(
            this,
            CHANNEL_ID
        )
            .setSmallIcon(
                R.drawable.ic_launcher_foreground
            )
            .setContentTitle(
                "LazyPC"
            )
            .setContentText(
                "Remote connection is active"
            )
            .setOngoing(true)
            .setCategory(
                NotificationCompat.CATEGORY_SERVICE
            )
            .setPriority(
                NotificationCompat.PRIORITY_LOW
            )
            .build()
    }

    private fun createNotificationChannel() {

        if (
            Build.VERSION.SDK_INT <
            Build.VERSION_CODES.O
        ) {
            return
        }

        val channel =
            NotificationChannel(
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
        ).createNotificationChannel(
            channel
        )
    }

    // =====================================================================
    // SERVICE DESTROY
    // =====================================================================

    override fun onDestroy() {

        Log.w(
            TAG,
            "🛑 Foreground WebRTC service destroyed"
        )

        onVideoTrackChanged = null
        onCursorPosition = null
        onSignalingState = null
        onSessionState = null
        onDirectSessionState = null

        pendingPairingPayload = null
        pendingPcId = null
        pendingTrustedPcCode = null
        trustedAttemptActive = false

        sessionTimeoutJob?.cancel()
        sessionTimeoutJob = null
        directSessionTimeoutJob?.cancel()
        directSessionTimeoutJob = null

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

        fun service():
                WebRTCForegroundService {
            return this@WebRTCForegroundService}}}
