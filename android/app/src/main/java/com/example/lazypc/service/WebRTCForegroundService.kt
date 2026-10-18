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
import com.example.lazypc.security.SecureLinkV4
import com.example.lazypc.security.SecureLinkNoiseKeyStore
import com.example.lazypc.security.SecureLinkNoiseSession
import com.example.lazypc.security.SecureLinkV4PairingHandshake
import com.example.lazypc.security.SecureLinkStrongBox
import java.security.Signature
import android.util.Base64
import com.example.lazypc.network.SecureLinkV4Signaling
import org.json.JSONObject
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.VideoTrack
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withContext


class WebRTCForegroundService : Service() {

    companion object {
        private const val TAG = "WEBRTC_SERVICE"
        private const val CHANNEL_ID = "lazypc_webrtc"
        private const val NOTIFICATION_ID = 1001
        private const val SESSION_TIMEOUT_MS = 30_000L
        private const val ORDINARY_AUTH_TIMEOUT_MS = 60_000L

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
    private var onSessionError: ((String) -> Unit)? = null
    private var onTrustedPcPaired: ((String, String?) -> Unit)? = null
    private var onSecureLinkPaired: ((String, String) -> Unit)? = null
    private var onDirectSessionState: ((Boolean, Boolean, String?) -> Unit)? = null
    private var onOrdinaryAuthRequired: (() -> Unit)? = null
    private var onPcStatus: ((String, Boolean) -> Unit)? = null

    private var sessionConnecting = false
    private var sessionConnected = false
    private var sessionGeneration = 0L
    private var sessionTimeoutJob: Job? = null
    private var signalingReconnectJob: Job? = null
    private var signalingRetryDelayMs = 2_000L
    private var directSessionTimeoutJob: Job? = null

    /*
     * Existing Trusted Device pairing state.
     *
     * Completely separate from direct PC selection.
     */
    private var pendingPairingPayload: String? = null
    private var pendingPairingPcIdentityPublic: String? = null

    // Secure Link v4 transport staging; separate from legacy pairing state.
    private var pendingSecureLinkPairingRoom: ByteArray? = null
    private var secureLinkV4Signaling: SecureLinkV4Signaling? = null
    private var pendingSecureLinkInvitation: SecureLinkV4.Invitation? = null
    private var secureLinkPairingHandshake: SecureLinkV4PairingHandshake? = null
    private var secureLinkEnrollmentKey: SecureLinkStrongBox.EnrollmentKey? = null
    private var secureLinkEnrollmentSignature: Signature? = null
    private var secureLinkPair1Pending = false
    private var secureSessionRoom: ByteArray? = null
    private var secureSessionPcStatic: ByteArray? = null
    private var secureSessionPhoneStatic: ByteArray? = null
    private var secureSessionNoise: SecureLinkNoiseSession? = null
    private var secureSessionHandshakeHash: ByteArray? = null
    private var secureSessionFpPhone: ByteArray? = null
    private var secureSessionFpPc: ByteArray? = null
    private var secureSessionAlias: String? = null
    private var secureSessionHelloPending = false
    private var secureSessionAuthorized = false
    private var onSecureLinkSas: ((String, Signature, (Signature?) -> Unit) -> Unit)? = null
    private var onSecureLinkCodeAccepted: (() -> Unit)? = null
    private var onSecureLinkAuthPrompt: ((Signature, (Signature?) -> Unit) -> Unit)? = null

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

            if (!connected) {
                scheduleSignalingReconnect()
            }

            if (!connected && secureSessionRoom != null) {
                failSecureLinkSession("signaling disconnected")
                return@setOnConnectionState
            }

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
                signalingReconnectJob?.cancel()
                signalingReconnectJob = null
                signalingRetryDelayMs = 2_000L

                sendPendingSecureLinkSubscription()

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

        ws.setOnPcStatus { pcCode, online ->
            onPcStatus?.invoke(pcCode, online)
        }

        webrtc = WebRTCClient(
            context = this,
            eglContext = eglBase.eglBaseContext,

            onFrame = frameCallback@{ track ->

                if (secureSessionRoom != null && !secureSessionAuthorized) {
                    // The remote track may be negotiated before StrongBox auth.
                    // Do not expose it to the UI until Windows opens its media gate.
                    currentVideoTrack = track
                    Log.d(TAG, "Secure Link video track negotiated; waiting for auth_complete")
                    return@frameCallback
                }

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
                // Never send ICE candidates as plaintext signaling. Secure Link v4
                // gathers them into SDP before the Noise-protected hello/reply.
                Log.v(TAG, "ICE candidate gathered for protected SDP (${candidate.sdpMid})")
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

        webrtc.onSecureAuthText = { text -> handleSecureSessionAuthChallenge(text) }
        webrtc.init()
        webrtc.createPeerConnection()

        // Signaling is a background dependency of the app, not something that
        // should wait until the user starts a remote session or scans a QR.
        Log.i(TAG, "Connecting to signaling endpoint: $SIGNALING_URL")
        ws.connect()
    }

    private fun scheduleSignalingReconnect() {
        if (signalingReconnectJob?.isActive == true) return

        signalingReconnectJob = serviceScope.launch {
            while (true) {
                val waitMs = signalingRetryDelayMs
                Log.w(TAG, "Signaling is offline; retrying in ${waitMs}ms")
                delay(waitMs)

                if (!::ws.isInitialized) return@launch
                if (ws.isOpen()) return@launch

                try {
                    ws.connect()
                } catch (error: Throwable) {
                    Log.e(TAG, "Could not start signaling reconnect", error)
                }

                signalingRetryDelayMs = (signalingRetryDelayMs * 2).coerceAtMost(30_000L)
                // A failed WebSocket attempt invokes onConnectionState(false),
                // which leaves this loop responsible for the next retry.
                // If connect is still in progress, wait before checking again.
                delay(1_000L)
                if (ws.isOpen()) return@launch
            }
        }
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
            (Boolean, Boolean) -> Unit,

        onSessionError:
        ((String) -> Unit)? = null
    ) {
        this.onVideoTrackChanged =
            onVideoTrackChanged

        this.onCursorPosition =
            onCursorPosition

        this.onSignalingState =
            onSignalingState

        this.onSessionState =
            onSessionState

        this.onSessionError =
            onSessionError

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
        callback: (String, String?) -> Unit
    ) {
        onTrustedPcPaired = callback
    }

    /** Called after Secure Link v4 pairing is authenticated and persisted. */
    fun registerSecureLinkPairedCallback(callback: (pcIdentityPublic: String, hardwareAlias: String) -> Unit) {
        onSecureLinkPaired = callback
    }

    /** UI callback displays the SAS and completes StrongBox biometric signing. */
    fun registerSecureLinkPairingCallback(
        callback: (String, Signature, (Signature?) -> Unit) -> Unit
    ) {
        onSecureLinkSas = callback
    }

    /** Called only after the Windows UI accepted the SAS and its proof verified. */
    fun registerSecureLinkCodeAcceptedCallback(callback: () -> Unit) {
        onSecureLinkCodeAccepted = callback
    }

    /** UI must authenticate biometrically before the StrongBox session signature is used. */
    fun registerSecureLinkAuthPrompt(callback: (Signature, (Signature?) -> Unit) -> Unit) {
        onSecureLinkAuthPrompt = callback
    }

    fun registerPcStatusCallback(
        callback: (String, Boolean) -> Unit
    ) {
        onPcStatus = callback
        ws.setOnPcStatus(callback)
    }

    fun requestPcStatus(pcCode: String): Boolean {
        if (!ws.isSignalingReady()) {
            ws.connect()
            return false
        }

        return ws.requestPcStatus(pcCode)
    }

    fun registerOrdinaryAuthCallback(
        callback: () -> Unit
    ) {
        onOrdinaryAuthRequired = callback
    }

    fun submitOrdinarySecret(secret: String): Boolean {
        return ws.submitOrdinarySecret(secret)
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
        onSessionError = null
        onTrustedPcPaired = null
        onSecureLinkPaired = null
        onDirectSessionState = null
        onOrdinaryAuthRequired = null
        onSecureLinkSas = null
        onSecureLinkCodeAccepted = null
        onSecureLinkAuthPrompt = null
        onSecureLinkAuthPrompt = null
    }

    // =====================================================================
    // TRUSTED DEVICE CONNECTION
    // =====================================================================

    /** Start a Secure Link v4 session for a PC the user explicitly selected on Home. */
    fun connectTrusted(pcIdentityPublic: String, hardwareAlias: String) {
        if (sessionConnecting || sessionConnected || directAttemptActive) {
            Log.w(TAG, "Secure Link v4 connect ignored: another session is active")
            onSessionError?.invoke("Уже выполняется другое подключение")
            return
        }
        if (pcIdentityPublic.isBlank() || hardwareAlias.isBlank()) {
            Log.e(TAG, "Secure Link v4 connect rejected: missing trusted identity or StrongBox alias")
            onSessionError?.invoke("Не хватает данных доверенного устройства")
            return
        }
        try {
            val pcStatic = Base64.decode(
                pcIdentityPublic,
                Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING
            )
            check(pcStatic.size == 32) { "Invalid pinned PC X25519 public key" }
            Log.i(TAG, "User selected a trusted Secure Link v4 PC; starting authenticated session")
            beginSecureLinkSession(pcStatic, hardwareAlias)
        } catch (error: Throwable) {
            Log.e(TAG, "Could not start Secure Link v4 session", error)
            onSessionError?.invoke("Не удалось начать подключение: ${error.message ?: "ошибка данных"}")
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
        Log.e(TAG, "Legacy create_session is disabled. Secure Link v4 is mandatory.")
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
    fun connectToPc(pcId: String) {
        Log.e(TAG, "Plain PC-ID WebRTC signaling is disabled. Secure Link v4 is mandatory.")
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

        // Secure Link v4 has a URI QR and room-based signaling. No legacy QR
        // format is accepted by the new protocol.
        if (!qrPayload.startsWith("lazypc://pair/4?")) {
            Log.e(TAG, "Rejected legacy pairing QR: Secure Link v4 QR is required")
            return
        }
        if (qrPayload.startsWith("lazypc://pair/4?")) {
            try {
                val invitation = SecureLinkV4.parseQrPayload(qrPayload)
                clearSecureLinkPairing("new invitation")
                pendingSecureLinkInvitation = invitation
                pendingSecureLinkPairingRoom = invitation.pairingRoom()
                secureLinkV4Signaling = SecureLinkV4Signaling(ws)
                secureLinkPair1Pending = true
                Log.i(TAG, "Secure Link v4 QR accepted; subscribing to pairing room")
                if (ws.isOpen()) {
                    sendPendingSecureLinkSubscription()
                } else {
                    ws.connect()
                }
            } catch (error: Exception) {
                pendingSecureLinkPairingRoom = null
                secureLinkV4Signaling = null
                Log.e(TAG, "Secure Link v4 QR rejected", error)
            }
            return
        }

        return
    }

    private fun sendPendingSecureLinkSubscription() {
        if (!ws.isOpen()) return
        val signaling = secureLinkV4Signaling ?: return
        val pairRoom = pendingSecureLinkPairingRoom
        val sessionRoom = secureSessionRoom
        val room = pairRoom ?: sessionRoom ?: return
        if (signaling.subscribe(room)) {
            Log.i(TAG, if (pairRoom != null) "Secure Link v4 pairing room subscription sent" else "Secure Link v4 session room subscription sent")
        } else {
            Log.e(TAG, "Secure Link v4 room subscription could not be sent")
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

    private fun sendSecureLinkPair1() {
        val invitation = pendingSecureLinkInvitation ?: return
        val room = pendingSecureLinkPairingRoom ?: return
        val signaling = secureLinkV4Signaling ?: return
        if (!secureLinkPair1Pending || !ws.isOpen()) return
        try {
            val identity = SecureLinkNoiseKeyStore(this).loadOrCreate()
            val handshake = try {
                SecureLinkV4PairingHandshake(invitation, identity)
            } finally {
                identity.privateKey.fill(0)
            }
            val message = handshake.createPair1()
            check(signaling.send(room, "pair1", message)) { "Could not send pair1" }
            secureLinkPairingHandshake = handshake
            secureLinkPair1Pending = false
            Log.i(TAG, "Secure Link v4 pair1 sent (${message.size} bytes)")
        } catch (error: Throwable) {
            Log.e(TAG, "Secure Link v4 pair1 failed", error)
            clearSecureLinkPairing("pair1 failed")
        }
    }

    private fun handleSecureLinkPairingEnvelope(kind: String, data: ByteArray) {
        val handshake = secureLinkPairingHandshake
        val room = pendingSecureLinkPairingRoom
        val signaling = secureLinkV4Signaling
        if (handshake == null || room == null || signaling == null) {
            Log.w(TAG, "Ignoring Secure Link $kind without an active pairing")
            return
        }
        try {
            when (kind) {
                "pair2" -> {
                    val code = handshake.receivePair2(data)
                    val invitation = pendingSecureLinkInvitation ?: error("Invitation disappeared")
                    val strongBox = SecureLinkStrongBox(this)
                    val enrollment = strongBox.createFreshPairingKey(invitation.nonce)
                    secureLinkEnrollmentKey = enrollment
                    val transcript = handshake.pairingTranscript(enrollment)
                    val prepareSignature = strongBox.prepareSignatureForBiometric(enrollment.alias)
                    secureLinkEnrollmentSignature = prepareSignature
                    val callback = onSecureLinkSas
                    if (callback == null) error("Pairing UI is not attached; cannot display SAS or request biometric")
                    callback(code, prepareSignature) { signedSignature ->
                        serviceScope.launch(Dispatchers.IO) {
                            try {
                                if (signedSignature == null) error("Biometric signing cancelled")
                                val signature = strongBox.finishSignature(signedSignature, transcript)
                                val pair3 = handshake.createPair3(
                                    enrollment, signature, Build.MANUFACTURER ?: "unknown",
                                    Build.MODEL ?: "unknown", Build.VERSION.RELEASE ?: "unknown"
                                )
                                if (!signaling.send(room, "pair3", pair3)) error("Could not send pair3")
                                Log.i(TAG, "Secure Link v4 pair3 sent (${pair3.size} bytes)")
                            } catch (error: Throwable) {
                                Log.e(TAG, "Secure Link v4 StrongBox enrollment failed", error)
                                clearSecureLinkPairing("pair3 failed")
                            } finally {
                                transcript.fill(0)
                            }
                        }
                    }
                    Log.i(TAG, "Secure Link v4 pair2 accepted; StrongBox biometric authorized, awaiting Windows code acceptance")
                }
                "code_ok" -> {
                    check(handshake.verifyCodeAcceptedProof(data)) {
                        "Windows code-accepted proof is invalid"
                    }
                    Log.i(TAG, "Secure Link v4 Windows accepted the pairing code; biometric may start")
                    onSecureLinkCodeAccepted?.invoke()
                        ?: error("Pairing UI is not attached; cannot request biometric")
                }
                "pair4" -> {
                    val paired = handshake.receivePair4(data)
                    if (!paired) error("Windows rejected the pairing")
                    val invitation = pendingSecureLinkInvitation ?: error("Invitation disappeared")
                    val enrollment = secureLinkEnrollmentKey ?: error("Enrollment key missing")
                    // Pin the PC Noise identity and StrongBox alias only after authenticated PAIRED.
                    val saved = getSharedPreferences("secure_link_v4_trusted", MODE_PRIVATE).edit()
                        .putString("pc_static_" + SecureLinkV4.b64UrlEncode(invitation.pcStaticPublic),
                            SecureLinkV4.b64UrlEncode(invitation.pcStaticPublic))
                        .putString("hw_alias_" + SecureLinkV4.b64UrlEncode(invitation.pcStaticPublic), enrollment.alias)
                        .commit()
                    check(saved) { "Could not persist trusted Secure Link device" }
                    val pcStatic = SecureLinkV4.b64UrlEncode(invitation.pcStaticPublic)
                    val alias = enrollment.alias
                    Log.i(TAG, "Secure Link v4 pairing completed; PC identity pinned; returning to Home")
                    // Notify the UI only after durable trust storage. Do not start Noise/WebRTC
                    // or trigger the separate session biometric until the user selects this PC.
                    onSecureLinkPaired?.invoke(pcStatic, alias)
                        ?: Log.w(TAG, "Secure Link v4 paired, but Home UI callback is not attached")
                    clearSecureLinkPairing("paired", preserveTrust = true)
                }
                else -> Log.w(TAG, "Ignoring unexpected Secure Link pairing kind=$kind")
            }
        } catch (error: Throwable) {
            Log.e(TAG, "Secure Link v4 pairing message $kind failed", error)
            clearSecureLinkPairing("$kind failed")
        }
    }

    private fun beginSecureLinkSession(pcStaticPublic: ByteArray, hardwareAlias: String) {
        if (sessionConnecting || sessionConnected || directAttemptActive) {
            failSecureLinkSession("another session is already active")
        }
        sessionGeneration++
        sessionConnecting = true
        sessionConnected = false
        onSessionState?.invoke(true, false)
        startSessionTimeout(sessionGeneration)

        secureSessionPcStatic = pcStaticPublic.copyOf()
        secureSessionAlias = hardwareAlias
        secureSessionRoom = SecureLinkV4.sessionRoom(pcStaticPublic)
        secureLinkV4Signaling = SecureLinkV4Signaling(ws)
        secureSessionHelloPending = true
        secureSessionAuthorized = false
        secureSessionPhoneStatic = null
        secureSessionHandshakeHash = null
        secureSessionFpPhone = null
        secureSessionFpPc = null
        secureSessionNoise?.close()
        secureSessionNoise = null

        try {
            // Do not reuse any previous/legacy PeerConnection for a v4 session.
            webrtc.resetPeerConnection()
            if (ws.isOpen()) sendPendingSecureLinkSubscription() else ws.connect()
            Log.i(TAG, "Secure Link v4 session started; waiting for secure room subscription")
        } catch (error: Throwable) {
            Log.e(TAG, "Could not initialize Secure Link v4 session", error)
            failSecureLinkSession("WebRTC initialization failed")
        }
    }

    private fun sendSecureSessionHello() {
        if (!secureSessionHelloPending || !ws.isOpen()) return
        val room = secureSessionRoom ?: return
        val pcStatic = secureSessionPcStatic ?: return
        val signaling = secureLinkV4Signaling ?: return
        secureSessionHelloPending = false
        val generation = sessionGeneration
        serviceScope.launch(Dispatchers.IO) {
            var identity: SecureLinkNoiseKeyStore.StaticIdentity? = null
            var noise: SecureLinkNoiseSession? = null
            try {
                identity = SecureLinkNoiseKeyStore(this@WebRTCForegroundService).loadOrCreate()
                val offer = webrtc.createSecureOffer()
                if (generation != sessionGeneration || !sessionConnecting) return@launch
                val fpPhone = SecureLinkV4.sdpFingerprint(offer)
                noise = SecureLinkNoiseSession.sessionInitiator(identity.privateKey, pcStatic)
                val hello = JSONObject().apply {
                    put("ts", System.currentTimeMillis() / 1000.0)
                    put("sdp", offer)
                }.toString().toByteArray(StandardCharsets.UTF_8)
                val message = noise.writeMessage(hello)
                if (generation != sessionGeneration || !sessionConnecting) return@launch
                check(signaling.send(room, "hello", message)) { "Could not send secure hello" }
                if (generation != sessionGeneration || !sessionConnecting) return@launch
                secureSessionPhoneStatic = identity.publicKey.copyOf()
                secureSessionFpPhone = fpPhone
                secureSessionNoise = noise
                noise = null
                Log.i(TAG, "Secure Link v4 Noise IK hello sent; SDP/ICE remained inside Noise")
            } catch (error: Throwable) {
                Log.e(TAG, "Secure Link v4 hello failed", error)
                if (generation == sessionGeneration && sessionConnecting) {
                    failSecureLinkSession("Noise hello failed")
                }
            } finally {
                identity?.privateKey?.fill(0)
                noise?.close()
            }
        }
    }

    private fun handleSecureLinkSessionEnvelope(kind: String, data: ByteArray) {
        if (kind != "reply") {
            Log.w(TAG, "Unexpected Secure Link session message kind=$kind")
            return
        }
        val generation = sessionGeneration
        serviceScope.launch(Dispatchers.IO) {
            try {
                if (generation != sessionGeneration || !sessionConnecting) return@launch
                val noise = secureSessionNoise ?: error("No active Noise session")
                val plain = noise.readMessage(data)
                if (generation != sessionGeneration || !sessionConnecting) return@launch
                check(noise.isHandshakeFinished) { "Noise IK handshake did not finish" }
                val answer = JSONObject(String(plain, StandardCharsets.UTF_8)).getString("sdp")
                val fpPc = SecureLinkV4.sdpFingerprint(answer)
                if (generation != sessionGeneration || !sessionConnecting) return@launch
                secureSessionHandshakeHash = noise.handshakeHash()
                secureSessionFpPc = fpPc
                webrtc.applySecureAnswer(answer)
                Log.i(TAG, "Secure Link v4 Noise IK completed; authenticated SDP answer applied")
            } catch (error: Throwable) {
                Log.e(TAG, "Secure Link v4 reply rejected", error)
                if (generation == sessionGeneration && sessionConnecting) {
                    failSecureLinkSession("Noise reply or SDP answer invalid")
                }
            }
        }
    }

    private fun handleSecureSessionAuthChallenge(text: String) {
        val generation = sessionGeneration
        serviceScope.launch(Dispatchers.IO) {
            try {
                if (generation != sessionGeneration || !sessionConnecting) return@launch
                val msg = JSONObject(text)
                when (msg.optString("type")) {
                    "auth_complete" -> {
                        if (generation != sessionGeneration || !sessionConnecting) return@launch
                        require(msg.optString("scope") == "session") { "Unexpected auth completion scope" }
                        secureSessionAuthorized = true
                        sessionTimeoutJob?.cancel()
                        sessionTimeoutJob = null
                        sessionConnecting = false
                        sessionConnected = true
                        onSessionState?.invoke(false, true)
                        currentVideoTrack?.let { onVideoTrackChanged?.invoke(it) }
                        Log.i(TAG, "Secure Link v4 authorization confirmed; video is now visible")
                        return@launch
                    }
                    "auth_challenge" -> Unit
                    else -> error("Unexpected auth-channel message type")
                }
                val scope = msg.getString("scope")
                require(scope == "session") { "Unsupported authorization scope" }
                val nonce = Base64.decode(msg.getString("nonce"), Base64.DEFAULT)
                val sessionId = Base64.decode(msg.getString("session_id"), Base64.DEFAULT)
                require(nonce.size == 32 && sessionId.size == 16) { "Invalid auth challenge sizes" }
                val handshakeHash = secureSessionHandshakeHash ?: error("Noise handshake hash missing")
                val pcStatic = secureSessionPcStatic ?: error("PC identity missing")
                val phoneStatic = secureSessionPhoneStatic ?: error("Phone identity missing")
                val fpPhone = secureSessionFpPhone ?: error("Phone DTLS fingerprint missing")
                val fpPc = secureSessionFpPc ?: error("PC DTLS fingerprint missing")
                val alias = secureSessionAlias ?: error("StrongBox key alias missing")
                val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                val hwDer = keyStore.getCertificate(alias)?.publicKey?.encoded ?: error("StrongBox public key unavailable")
                val transcript = SecureLinkV4.sessionTranscript(scope, handshakeHash, pcStatic, phoneStatic, hwDer, fpPc, fpPhone, nonce, sessionId)
                val signer = SecureLinkStrongBox(this@WebRTCForegroundService).prepareSignatureForBiometric(alias)
                val callback = onSecureLinkAuthPrompt ?: error("Biometric UI is not attached")
                if (generation != sessionGeneration || !sessionConnecting) {
                    transcript.fill(0)
                    return@launch
                }
                withContext(Dispatchers.Main) {
                    if (generation != sessionGeneration || !sessionConnecting) {
                        transcript.fill(0)
                        return@withContext
                    }
                    callback(signer) { authorizedSignature ->
                        serviceScope.launch(Dispatchers.IO) {
                            try {
                                if (generation != sessionGeneration || !sessionConnecting) return@launch
                                if (authorizedSignature == null) error("Biometric authorization cancelled")
                                val signature = SecureLinkStrongBox(this@WebRTCForegroundService).finishSignature(authorizedSignature, transcript)
                                val response = JSONObject().apply {
                                    put("type", "auth_response")
                                    put("scope", scope)
                                    put("session_id", Base64.encodeToString(sessionId, Base64.NO_WRAP))
                                    put("signature", Base64.encodeToString(signature, Base64.NO_WRAP))
                                }
                                if (generation != sessionGeneration || !sessionConnecting) return@launch
                                check(webrtc.sendSecureAuthText(response.toString())) { "Auth DataChannel is not open" }
                                Log.i(TAG, "Secure Link v4 StrongBox auth response sent")
                            } catch (error: Throwable) {
                                Log.e(TAG, "Secure Link v4 StrongBox authorization failed", error)
                                if (generation == sessionGeneration && sessionConnecting) {
                                    failSecureLinkSession("StrongBox authorization failed")
                                }
                            } finally {
                                transcript.fill(0)
                            }
                        }
                    }
                }
            } catch (error: Throwable) {
                Log.e(TAG, "Invalid Secure Link auth challenge", error)
                if (generation == sessionGeneration && sessionConnecting) {
                    failSecureLinkSession("Invalid auth challenge")
                }
            }
        }
    }

    private fun failSecureLinkSession(reason: String) {
        Log.e(TAG, "Secure Link v4 session failed: $reason")
        val wasActive = sessionConnecting || sessionConnected || secureSessionRoom != null
        // Invalidate timeout and asynchronous work associated with this attempt.
        sessionGeneration++
        sessionTimeoutJob?.cancel()
        sessionTimeoutJob = null
        sessionConnecting = false
        sessionConnected = false
        secureSessionHelloPending = false
        secureSessionAuthorized = false
        secureSessionNoise?.close()
        secureSessionNoise = null
        secureSessionRoom?.fill(0)
        secureSessionRoom = null
        secureSessionPcStatic?.fill(0)
        secureSessionPcStatic = null
        secureSessionPhoneStatic?.fill(0)
        secureSessionPhoneStatic = null
        secureSessionHandshakeHash?.fill(0)
        secureSessionHandshakeHash = null
        secureSessionFpPhone = null
        secureSessionFpPc = null
        secureSessionAlias = null
        try { webrtc.resetPeerConnection() } catch (_: Throwable) {}
        if (wasActive) {
            currentVideoTrack = null
            onVideoTrackChanged?.invoke(null)
            onSessionState?.invoke(false, false)
            if (reason != "user disconnected") {
                onSessionError?.invoke(
                    when (reason) {
                        "Connection timeout" -> "Не удалось подключиться: истекло время ожидания"
                        "signaling disconnected" -> "Соединение с сервером сигнализации потеряно"
                        "Noise hello failed" -> "Не удалось установить защищённое соединение"
                        "Noise reply or SDP answer invalid" -> "Компьютер вернул некорректный ответ"
                        "StrongBox authorization failed" -> "Не удалось подтвердить подключение"
                        "Invalid auth challenge" -> "Не удалось проверить запрос авторизации"
                        "WebRTC initialization failed" -> "Не удалось инициализировать WebRTC"
                        else -> "Не удалось подключиться ($reason)"
                    }
                )
            }
        }
    }

    private fun clearSecureLinkPairing(reason: String, preserveTrust: Boolean = false) {
        Log.i(TAG, "Clearing Secure Link pairing state: $reason")
        secureLinkPairingHandshake?.close()
        secureLinkPairingHandshake = null
        secureLinkEnrollmentSignature = null
        if (!preserveTrust) {
            secureLinkEnrollmentKey?.let { key ->
                try { SecureLinkStrongBox(this).deletePairingKey(key.alias) }
                catch (error: Throwable) { Log.w(TAG, "Could not remove failed pairing key", error) }
            }
        }
        secureLinkEnrollmentKey = null
        secureLinkPair1Pending = false
        pendingSecureLinkPairingRoom?.fill(0)
        pendingSecureLinkPairingRoom = null
        pendingSecureLinkInvitation?.let {
            it.psk.fill(0)
            it.nonce.fill(0)
            it.pcStaticPublic.fill(0)
        }
        pendingSecureLinkInvitation = null
        secureLinkV4Signaling = null
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
        if (secureSessionRoom != null) {
            failSecureLinkSession(reason)
            return
        }
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
        pendingPairingPcIdentityPublic = null
        clearSecureLinkPairing("service destroyed")
        onSecureLinkSas = null
        onSecureLinkCodeAccepted = null
        onSecureLinkAuthPrompt = null
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

        if (secureSessionRoom != null || sessionConnecting || sessionConnected) {
            failSecureLinkSession("user disconnected")
            ws.close()
            return
        }

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
        pendingPairingPcIdentityPublic = null
        clearSecureLinkPairing("service destroyed")
        onSecureLinkSas = null
        onSecureLinkCodeAccepted = null
        onSecureLinkAuthPrompt = null
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

            if (json.optString("type") in setOf("offer", "answer", "candidate")) {
                Log.e(TAG, "Dropped plaintext SDP/ICE signaling; Secure Link v4 is mandatory")
                return
            }

            when (
                json.optString("type")
            ) {
                "secure_link" -> {
                    val envelope = secureLinkV4Signaling?.parseIncoming(text)
                    val pairRoom = pendingSecureLinkPairingRoom
                    val sessionRoom = secureSessionRoom
                    when {
                        envelope == null -> Log.w(TAG, "Dropped malformed Secure Link v4 envelope")
                        pairRoom != null && pairRoom.contentEquals(envelope.room) -> handleSecureLinkPairingEnvelope(envelope.kind, envelope.data)
                        sessionRoom != null && sessionRoom.contentEquals(envelope.room) -> handleSecureLinkSessionEnvelope(envelope.kind, envelope.data)
                        else -> Log.w(TAG, "Dropped Secure Link v4 message for an unexpected room")
                    }
                    return
                }

                "secure_link_subscribe_result" -> {
                    val ok = json.optBoolean("ok", false)
                    val roomText = json.optString("room")
                    Log.i(TAG, "Secure Link v4 room subscription result: $ok room=$roomText")
                    if (!ok) {
                        if (pendingSecureLinkPairingRoom != null) clearSecureLinkPairing("pairing room subscription rejected")
                        if (secureSessionRoom != null) failSecureLinkSession("session room subscription rejected")
                    } else if (secureLinkPair1Pending && pendingSecureLinkPairingRoom?.let { SecureLinkV4.b64UrlEncode(it) == roomText } == true) {
                        sendSecureLinkPair1()
                    } else if (secureSessionHelloPending && secureSessionRoom?.let { SecureLinkV4.b64UrlEncode(it) == roomText } == true) {
                        sendSecureSessionHello()
                    }
                    return
                }

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
                        val pcIdentityPublic = pendingPairingPcIdentityPublic

                        Log.d(TAG, "✅ Trusted PC pairing completed: $normalized")
                        onTrustedPcPaired?.invoke(normalized, pcIdentityPublic)

                        pendingPairingPcIdentityPublic = null
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

                "ordinary_auth_challenge" -> {
                    if (directAttemptActive) {
                        Log.i(
                            TAG,
                            "🔐 Ordinary V2 authentication requires one-time secret"
                        )
                        onOrdinaryAuthRequired?.invoke()
                    }
                }

                "ordinary_auth_rejected" -> {
                    val reason = json.optString("reason", "unknown")
                    Log.e(TAG, "❌ Ordinary V2 authentication rejected: $reason")
                    failDirectConnection(
                        when (reason) {
                            "user_declined" -> "Подключение отклонено на компьютере"
                            "invalid_secret", "authentication_failed" -> "Неверный код компьютера"
                            "expired" -> "Код компьютера истёк"
                            "rate_limited" -> "Слишком много попыток"
                            else -> "Ошибка авторизации"
                        }
                    )
                }

                "connection_auth_rejected" -> {
                    val reason = json.optString(
                        "reason",
                        "unknown"
                    )

                    val userMessage =
                        when (reason) {
                            "user_declined" ->
                                "Подключение отклонено на компьютере"

                            "authentication_failed" ->
                                "Ошибка авторизации"

                            else ->
                                "Подключение отклонено"
                        }

                    Log.e(
                        TAG,
                        "❌ Direct connection rejected: $reason"
                    )

                    failDirectConnection(
                        userMessage
                    )
                }

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
        onSessionError = null
        onDirectSessionState = null

        pendingPairingPayload = null
        pendingPairingPcIdentityPublic = null
        clearSecureLinkPairing("service destroyed")
        onSecureLinkSas = null
        onSecureLinkCodeAccepted = null
        onSecureLinkAuthPrompt = null
        pendingPcId = null
        pendingTrustedPcCode = null
        trustedAttemptActive = false

        sessionTimeoutJob?.cancel()
        sessionTimeoutJob = null
        signalingReconnectJob?.cancel()
        signalingReconnectJob = null
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
