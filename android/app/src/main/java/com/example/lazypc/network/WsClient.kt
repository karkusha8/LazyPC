package com.example.lazypc.network

import android.content.Context
import android.util.Base64
import android.util.Log
import com.example.lazypc.security.SecurityKeyStore
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

class WsClient(
    private val context: Context,
    private val url: String,
) {

    private val client = OkHttpClient.Builder()
        .pingInterval(15, TimeUnit.SECONDS)
        .build()

    private var socket: WebSocket? = null
    private var socketOpen = false
    private var signalingReady = false
    private var manuallyClosed = false

    private var onText: ((String) -> Unit)? = null
    private var onConnectionState: ((Boolean) -> Unit)? = null
    private var onPcStatus: ((String, Boolean) -> Unit)? = null

    private val securityKeyStore = SecurityKeyStore()

    fun setOnTextMessage(callback: (String) -> Unit) {
        onText = callback
    }

    fun setOnConnectionState(callback: (Boolean) -> Unit) {
        onConnectionState = callback
    }

    fun setOnPcStatus(callback: (String, Boolean) -> Unit) {
        onPcStatus = callback
    }

    @Synchronized
    fun connect() {
        if (socket != null) return

        manuallyClosed = false
        socketOpen = false
        signalingReady = false

        val request = Request.Builder()
            .url(url)
            .build()

        socket = client.newWebSocket(request, listener)
    }

    @Synchronized
    fun reconnectNow() {
        manuallyClosed = false
        socketOpen = false
        signalingReady = false

        val old = socket
        socket = null
        old?.close(1000, "Reconnect")

        connect()
    }

    @Synchronized
    fun isConnected(): Boolean = socket != null

    /** True only while the WebSocket transport is OPEN. */
    @Synchronized
    fun isOpen(): Boolean = socket != null && socketOpen

    /**
     * True only after the client handshake has been sent.
     *
     * The application must use this for signaling requests such as find_pc.
     * A raw WebSocket OPEN is not enough because HELLO_CLIENT is sent from
     * onOpen().
     */
    @Synchronized
    fun isSignalingReady(): Boolean =
        socket != null && socketOpen && signalingReady

    fun sendText(text: String): Boolean {
        return socket?.send(text) == true
    }

    fun sendBinary(data: ByteArray): Boolean {
        return socket?.send(ByteString.of(*data)) == true
    }

    fun sendAnswer(sdp: String) {
        val json = JSONObject().apply {
            put("type", "answer")
            put("sdp", sdp)
        }
        sendText(json.toString())
    }

    fun sendOffer(sdp: String) {
        val json = JSONObject().apply {
            put("type", "offer")
            put("sdp", sdp)
        }
        sendText(json.toString())
    }

    fun sendCandidate(
        candidate: String,
        sdpMid: String?,
        sdpMLineIndex: Int,
    ) {
        val json = JSONObject().apply {
            put("type", "candidate")
            put("candidate", candidate)
            put("sdpMid", sdpMid)
            put("sdpMLineIndex", sdpMLineIndex)
        }
        sendText(json.toString())
    }

    fun sendJson(json: JSONObject): Boolean {
        return sendText(json.toString())
    }

    /**
     * Ordinary/direct connection:
     * asks the signaling server to locate the PC by its 9-digit public code.
     */
    fun findPc(pcId: String): Boolean {
        if (!isSignalingReady()) {
            Log.e(
                "LazyPC-Security",
                "❌ find_pc blocked: signaling handshake is not ready"
            )
            return false
        }

        val normalized = pcId.filter { it.isDigit() }

        if (normalized.length != 9) {
            Log.e(
                "LazyPC-Security",
                "Invalid PC code: expected 9 digits"
            )
            return false
        }

        val formatted = "${normalized.substring(0, 3)} " +
                "${normalized.substring(3, 6)} " +
                normalized.substring(6, 9)

        val json = JSONObject().apply {
            put("type", "find_pc")
            put("pc_id", formatted)
        }

        Log.i(
            "LazyPC-Security",
            "📤 find_pc sent: $formatted"
        )

        return sendText(json.toString())
    }

    /**
     * Ask signaling whether a concrete public PC code currently has
     * a connected Windows Agent.
     */
    fun requestPcStatus(pcCode: String): Boolean {
        if (!isSignalingReady()) {
            Log.e(
                "LazyPC-Security",
                "❌ get_pc_status blocked: signaling handshake is not ready"
            )
            return false
        }

        val normalized = pcCode.filter { it.isDigit() }

        if (normalized.length != 9) {
            Log.e(
                "LazyPC-Security",
                "Invalid PC code for status: expected 9 digits"
            )
            return false
        }

        val json = JSONObject().apply {
            put("type", "get_pc_status")
            put("pc_code", normalized)
        }

        return sendText(json.toString())
    }

    /**
     * Starts a Trusted Device connection to an already paired PC.
     *
     * This is NOT pairing/enrollment. The PC must already be trusted.
     * Signaling only routes this client to the selected PC.
     * Windows performs the actual Trusted Device cryptographic authentication.
     */
    fun connectTrusted(pcCode: String): Boolean {
        if (!isSignalingReady()) {
            Log.e(
                "LazyPC-Security",
                "❌ connect_trusted blocked: signaling handshake is not ready"
            )
            return false
        }

        val normalized = pcCode.filter { it.isDigit() }

        if (normalized.length != 9) {
            Log.e(
                "LazyPC-Security",
                "Invalid Trusted PC code: expected 9 digits"
            )
            return false
        }

        val formatted = "${normalized.substring(0, 3)} " +
                "${normalized.substring(3, 6)} " +
                normalized.substring(6, 9)

        val json = JSONObject().apply {
            put("type", "connect_trusted")
            put("pc_code", formatted)
        }

        Log.i(
            "LazyPC-Security",
            "📤 connect_trusted sent: $formatted"
        )

        return sendText(json.toString())
    }

    /**
     * Starts Trusted Device pairing using the short-lived QR token.
     *
     * This is the existing pairing model and remains completely separate
     * from ordinary/direct PC-code authentication.
     */
    fun startTrustedPairingSession(qrPayload: String) {
        val parts = qrPayload.split('|')

        require(parts.size == 5) {
            "Invalid LazyPC pairing QR"
        }

        require(parts[0] == "LAZYPC_PAIR_V2") {
            "Unsupported LazyPC pairing QR"
        }

        val token = parts[2]

        sendJson(
            JSONObject().apply {
                put("type", "create_session")
                put("pairing_token", token)
            }
        )
    }

    /**
     * Existing Trusted Device authentication path.
     *
     * IMPORTANT:
     * This is intentionally preserved. Do not replace this with the
     * ordinary/direct connection authentication below.
     */
    private fun handleAuthChallenge(json: JSONObject) {
        try {
            val version = json.optInt("version", -1)
            val algorithm = json.optString("algorithm")
            val challenge = json.optString("challenge")
            val pcIdentityPublic = json.optString("pc_identity_public")

            if (version != 3) {
                Log.e(
                    "LazyPC-Security",
                    "Unsupported AUTH challenge version"
                )
                return
            }

            if (algorithm != "ECDSA-P256-TRUSTED-V3") {
                Log.e(
                    "LazyPC-Security",
                    "Unsupported AUTH challenge algorithm"
                )
                return
            }

            if (challenge.isBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "AUTH challenge is empty"
                )
                return
            }

            if (pcIdentityPublic.isBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "AUTH challenge is missing PC identity"
                )
                return
            }

            securityKeyStore.ensureKeys()

            val identityPublic =
                securityKeyStore.identityPublicKeyBase64()

            securityKeyStore.ensureDeviceKeyForPc(
                pcIdentityPublic = pcIdentityPublic
            )

            val devicePublic =
                securityKeyStore.devicePublicKeyBase64(
                    pcIdentityPublic = pcIdentityPublic
                )

            val identityBindingSignature =
                securityKeyStore.identityBindingSignature(
                    context = context,
                    pcIdentityPublic = pcIdentityPublic
                )

            if (identityBindingSignature.isNullOrBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "Trusted Device identity binding is missing"
                )
                return
            }

            val deviceSignature =
                securityKeyStore.signAuthDevice(
                    pcIdentityPublic = pcIdentityPublic,
                    challenge = challenge
                )

            val response = JSONObject().apply {
                put("type", "auth_response")
                put("version", 3)
                put(
                    "algorithm",
                    "ECDSA-P256-TRUSTED-V3"
                )
                put(
                    "pc_identity_public",
                    pcIdentityPublic
                )
                put(
                    "identity_public",
                    identityPublic
                )
                put(
                    "device_public",
                    devicePublic
                )
                put(
                    "identity_binding_signature",
                    identityBindingSignature
                )
                put(
                    "device_signature",
                    deviceSignature
                )
            }

            if (sendText(response.toString())) {
                Log.i(
                    "LazyPC-Security",
                    "AUTH_RESPONSE sent"
                )
            } else {
                Log.e(
                    "LazyPC-Security",
                    "AUTH_RESPONSE send failed"
                )
            }

        } catch (error: Throwable) {
            Log.e(
                "LazyPC-Security",
                "AUTH challenge handling failed",
                error
            )
        }
    }

    /**
     * Ordinary/direct PC-code authentication.
     *
     * Windows sends:
     *
     * {
     *   "type": "connection_auth_challenge",
     *   "version": 1,
     *   "algorithm": "ECDSA-P256-IDENTITY-V1",
     *   "connection_id": "...",
     *   "pc_identity_public": "...",
     *   "challenge": "..."
     * }
     *
     * Android signs exactly:
     *
     * LAZYPC_CONNECTION_AUTH_V1|
     * <connection_id>|
     * <pc_identity_public>|
     * <identity_public>|
     * <challenge>
     *
     * The challenge is Base64 text exactly as received from Windows.
     */
    private fun handleConnectionAuthChallenge(
        json: JSONObject
    ) {
        try {
            val version = json.optInt("version", -1)
            val algorithm = json.optString("algorithm")
            val connectionId = json.optString("connection_id")
            val challenge = json.optString("challenge")
            val pcIdentityPublic = json.optString("pc_identity_public")

            if (version != 1) {
                Log.e(
                    "LazyPC-Security",
                    "Unsupported connection AUTH version: $version"
                )
                return
            }

            if (algorithm != "ECDSA-P256-IDENTITY-V1") {
                Log.e(
                    "LazyPC-Security",
                    "Unsupported connection AUTH algorithm: $algorithm"
                )
                return
            }

            if (connectionId.isBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "Connection AUTH challenge has no connection_id"
                )
                return
            }

            if (challenge.isBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "Connection AUTH challenge is empty"
                )
                return
            }

            if (pcIdentityPublic.isBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "Connection AUTH challenge has no PC identity"
                )
                return
            }

            securityKeyStore.ensureKeys()

            val identityPublic =
                securityKeyStore.identityPublicKeyBase64()

            val deviceId =
                deriveAndroidDeviceId(identityPublic)

            val transcript = (
                    "LAZYPC_CONNECTION_AUTH_V1|" +
                            "$connectionId|" +
                            "$pcIdentityPublic|" +
                            "$identityPublic|" +
                            challenge
                    ).toByteArray(StandardCharsets.UTF_8)

            /*
             * SecurityKeyStore already returns the signature
             * as a Base64 String.
             *
             * Do NOT Base64-encode it again here.
             */
            val identitySignature: String =
                securityKeyStore.signIdentity(
                    data = transcript
                )

            val response = JSONObject().apply {
                put(
                    "type",
                    "connection_auth_response"
                )

                put(
                    "version",
                    1
                )

                put(
                    "algorithm",
                    "ECDSA-P256-IDENTITY-V1"
                )

                put(
                    "connection_id",
                    connectionId
                )

                put(
                    "identity_public",
                    identityPublic
                )

                put(
                    "identity_signature",
                    identitySignature
                )

                put(
                    "device_id",
                    deviceId
                )
            }

            if (sendText(response.toString())) {
                Log.i(
                    "LazyPC-Security",
                    "🟢 CONNECTION_AUTH_RESPONSE sent"
                )
            } else {
                Log.e(
                    "LazyPC-Security",
                    "❌ CONNECTION_AUTH_RESPONSE send failed"
                )
            }

        } catch (error: Throwable) {
            Log.e(
                "LazyPC-Security",
                "❌ Connection AUTH challenge handling failed",
                error
            )
        }
    }

    /**
     * Same stable device-id derivation used by the Windows ConnectionAuth.
     *
     * SHA-256(identity_public DER)
     * -> URL-safe Base64 without '='
     * -> first 22 chars
     * -> "android-" prefix
     */
    private fun deriveAndroidDeviceId(
        identityPublicBase64: String
    ): String {
        val identityDer =
            Base64.decode(
                identityPublicBase64,
                Base64.DEFAULT
            )

        val digest =
            MessageDigest.getInstance("SHA-256")
                .digest(identityDer)

        val encoded =
            Base64.encodeToString(
                digest,
                Base64.URL_SAFE or
                        Base64.NO_WRAP or
                        Base64.NO_PADDING
            )

        return "android-" + encoded.take(22)
    }

    @Synchronized
    private fun handleSocketEnded(
        endedSocket: WebSocket,
        reason: String,
    ) {
        if (socket !== endedSocket) return

        socket = null
        socketOpen = false
        signalingReady = false

        onConnectionState?.invoke(false)
    }

    @Synchronized
    fun close() {
        manuallyClosed = true

        val current = socket

        socket = null
        socketOpen = false
        signalingReady = false

        current?.close(
            1000,
            "Client closed"
        )

        onConnectionState?.invoke(false)
    }

    private val listener =
        object : WebSocketListener() {

            override fun onOpen(
                ws: WebSocket,
                response: Response,
            ) {
                synchronized(this@WsClient) {
                    socket = ws
                    socketOpen = true
                }

                // IMPORTANT:
                // HELLO_CLIENT must be the first application-level message.
                // Do not notify the service that signaling is ready before it
                // has been sent, otherwise find_pc can race ahead of HELLO.
                val helloSent = ws.send("HELLO_CLIENT")

                synchronized(this@WsClient) {
                    signalingReady = helloSent
                }

                if (!helloSent) {
                    Log.e(
                        "LazyPC-Security",
                        "❌ HELLO_CLIENT send failed"
                    )

                    handleSocketEnded(
                        ws,
                        "hello_send_failed"
                    )
                    return
                }

                Log.i(
                    "LazyPC-Security",
                    "🟢 SIGNALING CONNECTED [CLIENT] — HELLO_CLIENT sent"
                )

                onConnectionState?.invoke(true)
            }

            override fun onMessage(
                ws: WebSocket,
                text: String,
            ) {
                try {
                    val json = JSONObject(text)

                    when (json.optString("type")) {
                        "pc_status" -> {
                            val pcCode = json.optString("pc_code")
                            val online = json.optBoolean("online", false)

                            if (pcCode.isNotBlank()) {
                                onPcStatus?.invoke(pcCode, online)
                            }

                            return
                        }

                        /*
                         * Old Trusted Device model.
                         */
                        "auth_challenge" -> {
                            handleAuthChallenge(json)
                            return
                        }

                        /*
                         * New ordinary/direct PC-code model.
                         */
                        "connection_auth_challenge" -> {
                            Log.i(
                                "LazyPC-Security",
                                "📥 CONNECTION_AUTH_CHALLENGE received"
                            )

                            handleConnectionAuthChallenge(json)
                            return
                        }
                    }

                } catch (error: Throwable) {
                    Log.e(
                        "LazyPC-Security",
                        "WebSocket JSON handling failed",
                        error
                    )
                }

                /*
                 * All non-auth signaling messages continue through
                 * the existing application handler.
                 */
                onText?.invoke(text)
            }

            override fun onMessage(
                ws: WebSocket,
                bytes: ByteString,
            ) {
                // Binary WebSocket messages are not used by signaling.
            }

            override fun onFailure(
                ws: WebSocket,
                t: Throwable,
                response: Response?,
            ) {
                Log.e(
                    "LazyPC-Security",
                    "🔴 SIGNALING FAILURE [CLIENT]: ${t.message}",
                    t
                )

                handleSocketEnded(
                    ws,
                    "failure"
                )
            }

            override fun onClosed(
                ws: WebSocket,
                code: Int,
                reason: String,
            ) {
                Log.i(
                    "LazyPC-Security",
                    "🔴 SIGNALING CLOSED [CLIENT]: $code $reason"
                )

                handleSocketEnded(
                    ws,
                    "closed"
                )
            }
        }
}