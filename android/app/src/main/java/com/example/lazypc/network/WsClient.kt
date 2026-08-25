package com.example.lazypc.network

import android.content.Context
import android.util.Log
import com.example.lazypc.security.SecurityKeyStore
import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class WsClient(
    private val context: Context,
    private val url: String,
) {

    private val client = OkHttpClient.Builder()
        .pingInterval(15, TimeUnit.SECONDS)
        .build()

    private var socket: WebSocket? = null
    private var manuallyClosed = false

    private var onText: ((String) -> Unit)? = null
    private var onConnectionState: ((Boolean) -> Unit)? = null

    private val securityKeyStore = SecurityKeyStore()

    fun setOnTextMessage(callback: (String) -> Unit) {
        onText = callback
    }

    fun setOnConnectionState(callback: (Boolean) -> Unit) {
        onConnectionState = callback
    }

    @Synchronized
    fun connect() {
        if (socket != null) return

        manuallyClosed = false

        val request = Request.Builder()
            .url(url)
            .build()

        socket = client.newWebSocket(request, listener)
    }

    @Synchronized
    fun reconnectNow() {
        manuallyClosed = false

        val old = socket
        socket = null
        old?.close(1000, "Reconnect")

        connect()
    }

    @Synchronized
    fun isConnected(): Boolean = socket != null

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

    fun sendJson(json: JSONObject) {
        sendText(json.toString())
    }

    /**
     * Starts Trusted Device pairing using the short-lived QR token.
     * The QR itself does not establish trust; enrollment is completed
     * later over the authenticated WebRTC DataChannel.
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
     * Normal Trusted Device authentication.
     *
     * Windows sends:
     *   - challenge
     *   - pc_identity_public
     *
     * The Android Device Key is selected by the PC identity.
     * Therefore one Android installation can safely have a separate
     * Device Key for every trusted PC.
     *
     * SecurityKeyStore is the authority for the exact signing transcript:
     *
     *   LAZYPC_AUTH_V2|DEVICE|<PC_IDENTITY_PUBLIC>|<CHALLENGE>
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
                    "Unsupported AUTH challenge version",
                )
                return
            }

            if (algorithm != "ECDSA-P256-TRUSTED-V3") {
                Log.e(
                    "LazyPC-Security",
                    "Unsupported AUTH challenge algorithm",
                )
                return
            }

            if (challenge.isBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "AUTH challenge is empty",
                )
                return
            }

            if (pcIdentityPublic.isBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "AUTH challenge is missing PC identity",
                )
                return
            }

            /*
             * Identity Key is global to this Android installation.
             */
            securityKeyStore.ensureKeys()

            val identityPublic =
                securityKeyStore.identityPublicKeyBase64()

            /*
             * Device Key is selected by the Windows PC identity.
             *
             * One Android installation may therefore have:
             *
             *   PC A -> D_A
             *   PC B -> D_B
             *   PC C -> D_C
             *
             * The PC identity received in this challenge is the
             * authoritative selector for the Device Key.
             */
            securityKeyStore.ensureDeviceKeyForPc(pcIdentityPublic)

            val devicePublic =
                securityKeyStore.devicePublicKeyBase64(
                    pcIdentityPublic = pcIdentityPublic,
                )

            /*
             * Stage 1:
             * Identity -> Device binding created during pairing.
             *
             * The binding is stored per PC identity.
             */
            val identityBindingSignature =
                securityKeyStore.identityBindingSignature(
                    context = context,
                    pcIdentityPublic = pcIdentityPublic,
                )

            if (identityBindingSignature.isNullOrBlank()) {
                Log.e(
                    "LazyPC-Security",
                    "Trusted Device identity binding is missing",
                )
                return
            }

            /*
             * Stage 2:
             * Fresh proof of possession of the Device private key.
             *
             * SecurityKeyStore signs:
             *
             * LAZYPC_AUTH_V2|DEVICE|<PC_IDENTITY_PUBLIC>|<CHALLENGE>
             */
            val deviceSignature =
                securityKeyStore.signAuthDevice(
                    pcIdentityPublic = pcIdentityPublic,
                    challenge = challenge,
                )

            val response =
                JSONObject().apply {
                    put("type", "auth_response")
                    put("version", 3)
                    put("algorithm", "ECDSA-P256-TRUSTED-V3")
                    put("pc_identity_public", pcIdentityPublic)
                    put("identity_public", identityPublic)
                    put("device_public", devicePublic)
                    put("identity_binding_signature", identityBindingSignature)
                    put("device_signature", deviceSignature)
                }

            if (sendText(response.toString())) {
                Log.i(
                    "LazyPC-Security",
                    "AUTH_RESPONSE sent",
                )
            } else {
                Log.e(
                    "LazyPC-Security",
                    "AUTH_RESPONSE send failed",
                )
            }

        } catch (error: Throwable) {
            Log.e(
                "LazyPC-Security",
                "AUTH challenge handling failed",
                error,
            )
        }
    }

    @Synchronized
    private fun handleSocketEnded(
        endedSocket: WebSocket,
        reason: String,
    ) {
        if (socket !== endedSocket) return

        socket = null
        onConnectionState?.invoke(false)
    }

    @Synchronized
    fun close() {
        manuallyClosed = true

        val current = socket
        socket = null

        current?.close(
            1000,
            "Client closed",
        )

        onConnectionState?.invoke(false)
    }

    private val listener = object : WebSocketListener() {

        override fun onOpen(
            ws: WebSocket,
            response: Response,
        ) {
            synchronized(this@WsClient) {
                socket = ws
            }

            onConnectionState?.invoke(true)
            ws.send("HELLO_CLIENT")
        }

        override fun onMessage(
            ws: WebSocket,
            text: String,
        ) {
            try {
                val json = JSONObject(text)

                if (json.optString("type") == "auth_challenge") {
                    handleAuthChallenge(json)
                    return
                }
            } catch (_: Throwable) {
                // Not a JSON/auth message; pass it to the normal handler.
            }

            onText?.invoke(text)
        }

        override fun onMessage(
            ws: WebSocket,
            bytes: ByteString,
        ) {
        }

        override fun onFailure(
            ws: WebSocket,
            t: Throwable,
            response: Response?,
        ) {
            handleSocketEnded(ws, "failure")
        }

        override fun onClosed(
            ws: WebSocket,
            code: Int,
            reason: String,
        ) {
            handleSocketEnded(ws, "closed")
        }
    }
}