package com.example.lazypc.webrtc

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.os.Build
import android.util.Log
import android.util.Base64
import org.json.JSONObject
import org.webrtc.*
import org.webrtc.audio.JavaAudioDeviceModule
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit

class WebRTCClient(

    private val context: Context,

    private val eglContext: EglBase.Context,

    private val onFrame: (VideoTrack) -> Unit,

    private val onIce: (IceCandidate) -> Unit,

    private val onCursorPosition: (Float, Float) -> Unit,

    private var audioDeviceModule: JavaAudioDeviceModule? = null




) {
    private val securityKeyStore =
        com.example.lazypc.security.SecurityKeyStore()
    private var hardwareAuthPending = false
    private var hardwareAuthorized = false

    private var trustedPairingInvitation: com.example.lazypc.security.TrustedPairing.Invitation? = null
    private var trustedPairingStarted = false

    companion object {

        private const val PACKET_CURSOR_POSITION =
            0x60

        private const val SESSION_CLOSE = "SESSION_CLOSE"
    }

    private lateinit var factory:
            PeerConnectionFactory

    private var peerConnection:
            PeerConnection? = null

    private var dataChannel:
            DataChannel? = null

    private var statsExecutor: ScheduledExecutorService? = null

    // Session diagnostics. These are diagnostic-only and do not affect media.
    private var diagnosticsStartedAtNs = 0L
    private val diagnosticsRttSamplesMs = mutableListOf<Double>()
    private var diagnosticsLastFreezeCount = -1L
    private var diagnosticsLastFreezeDuration = -1.0
    private var diagnosticsMaxVideoJitter = 0.0
    private var diagnosticsMaxVideoDecodeTime = 0.0
    private var diagnosticsLastVideoPackets = -1L
    private var diagnosticsLastVideoLost = -1L
    private var diagnosticsLastAudioPackets = -1L
    private var diagnosticsLastAudioLost = -1L

    fun init() {

        val options =
            PeerConnectionFactory.InitializationOptions
                .builder(context)
                .createInitializationOptions()

        PeerConnectionFactory.initialize(
            options
        )

        // Route the communication audio BEFORE WebRTC creates its audio
        // device module. This avoids initializing the AudioTrack on the
        // wrong Android output device.
        setupAudioRouting()

        audioDeviceModule =
            JavaAudioDeviceModule
                .builder(context)
                .setUseStereoOutput(true)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_MUSIC)
                        .build()
                )
                .createAudioDeviceModule()

        Log.d(
            "AUDIO",
            "🎵 WebRTC AudioTrack configured: USAGE_MEDIA + MUSIC + STEREO"
        )

        Log.d(
            "AUDIO",
            "🎧 JavaAudioDeviceModule created with stereo output requested"
        )

        factory =
            PeerConnectionFactory
                .builder()

                .setAudioDeviceModule(
                    audioDeviceModule
                )

                .setVideoDecoderFactory(
                    DefaultVideoDecoderFactory(
                        eglContext
                    )
                )

                .setVideoEncoderFactory(
                    DefaultVideoEncoderFactory(
                        eglContext,
                        true,
                        true
                    )
                )

                .createPeerConnectionFactory()
    }

    /**
     * Keep Android in normal media mode.
     *
     * WebRTC's playback AudioTrack is configured as MEDIA/MUSIC below.
     * No communication-device routing is used.
     */
    private fun setupAudioRouting() {
        val manager =
            context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

        manager.mode = AudioManager.MODE_NORMAL

        Log.d(
            "AUDIO",
            "🎵 Android media mode: mode=${manager.mode}, " +
                    "musicVolume=${manager.getStreamVolume(AudioManager.STREAM_MUSIC)}"
        )
    }

    private fun clearAudioRoute() {
        val manager =
            context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

        manager.mode = AudioManager.MODE_NORMAL

        Log.d(
            "AUDIO",
            "🔇 Audio routing released: mode=${manager.mode}"
        )
    }

    fun connectionState(): PeerConnection.PeerConnectionState? {
        return peerConnection?.connectionState()
    }

    fun iceConnectionState(): PeerConnection.IceConnectionState? {
        return peerConnection?.iceConnectionState()
    }

    fun isConnectionHealthy(): Boolean {
        val pc = peerConnection ?: return false
        return pc.connectionState() == PeerConnection.PeerConnectionState.CONNECTED ||
                pc.iceConnectionState() == PeerConnection.IceConnectionState.CONNECTED ||
                pc.iceConnectionState() == PeerConnection.IceConnectionState.COMPLETED
    }

    fun isConnectionDead(): Boolean {
        val pc = peerConnection ?: return true
        return pc.connectionState() == PeerConnection.PeerConnectionState.FAILED ||
                pc.connectionState() == PeerConnection.PeerConnectionState.CLOSED ||
                pc.iceConnectionState() == PeerConnection.IceConnectionState.FAILED ||
                pc.iceConnectionState() == PeerConnection.IceConnectionState.CLOSED
    }

    /**
     * Destroy only the current PeerConnection. The factory and audio module
     * stay alive so a new WebRTC session can be negotiated cheaply.
     */
    fun resetPeerConnection() {
        Log.d("WEBRTC", "♻️ Resetting PeerConnection for recovery")

        // Recovery is not an intentional user disconnect. Do not send
        // SESSION_CLOSE here, otherwise Windows would destroy the session
        // while Android is trying to rebuild it.
        hardwareAuthPending = false
        hardwareAuthorized = false
        trustedPairingStarted = false
        trustedPairingInvitation = null

        dataChannel?.close()
        dataChannel = null

        peerConnection?.close()
        peerConnection = null

        createPeerConnection()
    }

    fun createPeerConnection(): PeerConnection {

        val config =
            PeerConnection.RTCConfiguration(
                emptyList()
            )

        peerConnection =
            factory.createPeerConnection(

                config,

                object : PeerConnection.Observer {

                    override fun onIceCandidate(
                        candidate: IceCandidate?
                    ) {

                        candidate?.let {

                            Log.d(
                                "WEBRTC",
                                "📤 Local ICE candidate gathered"
                            )

                            onIce(it)
                        }
                    }

                    override fun onIceConnectionChange(
                        state: PeerConnection.IceConnectionState?
                    ) {

                        Log.d(
                            "WEBRTC",
                            "🧊 ICE connection state: $state"
                        )

                        if (
                            state ==
                            PeerConnection.IceConnectionState.CONNECTED
                            ||
                            state ==
                            PeerConnection.IceConnectionState.COMPLETED
                        ) {
                        }
                    }

                    override fun onTrack(
                        transceiver: RtpTransceiver?
                    ) {

                        val track =
                            transceiver
                                ?.receiver
                                ?.track()

                        if (track is VideoTrack) {

                            Log.d(
                                "WEBRTC",
                                "🎬 VIDEO TRACK RECEIVED"
                            )

                            onFrame(track)

                            return
                        }

                        if (track is AudioTrack) {

                            Log.d(
                                "AUDIO",
                                "🔊 AUDIO TRACK RECEIVED"
                            )

                        }
                    }

                    override fun onDataChannel(
                        channel: DataChannel?
                    ) {

                        if (channel == null) {

                            Log.e(
                                "DATA",
                                "❌ DataChannel == null"
                            )

                            return
                        }

                        Log.d(
                            "DATA",
                            "📡 DataChannel received"
                        )

                        dataChannel = channel

                        channel.registerObserver(

                            object : DataChannel.Observer {

                                override fun onBufferedAmountChange(
                                    previousAmount: Long
                                ) {

                                    Log.v(
                                        "DATA",
                                        "Buffered amount changed: $previousAmount"
                                    )
                                }

                                override fun onStateChange() {

                                    Log.d(
                                        "DATA",
                                        "STATE = ${channel.state()}"
                                    )

                                    if (channel.state() == DataChannel.State.OPEN) {
                                        sendTrustedPairingHello()
                                    }
                                }

                                override fun onMessage(
                                    buffer: DataChannel.Buffer
                                ) {

                                    /*
                                     * ==============================
                                     * BINARY MESSAGE
                                     * ==============================
                                     */

                                    if (buffer.binary) {

                                        val bytes =
                                            ByteArray(
                                                buffer.data.remaining()
                                            )

                                        buffer.data.get(bytes)

                                        handleBinaryMessage(
                                            bytes
                                        )

                                        return
                                    }

                                    /*
                                     * ==============================
                                     * TEXT MESSAGE
                                     * ==============================
                                     */

                                    val bytes =
                                        ByteArray(
                                            buffer.data.remaining()
                                        )

                                    buffer.data.get(bytes)

                                    val text =
                                        String(bytes)

                                    Log.d(
                                        "DATA",
                                        "📥 RX TEXT = $text"
                                    )

                                    if (handleTrustedPairingChallenge(text)) {
                                        return
                                    }

                                    if (handleHardwareAuthMessage(text)) {
                                        return
                                    }

                                    if (text == "PONG") {

                                        Log.d(
                                            "DATA",
                                            "✅ PONG RECEIVED"
                                        )
                                    }
                                }
                            }
                        )
                    }

                    override fun onSignalingChange(
                        state: PeerConnection.SignalingState?
                    ) {
                    }

                    override fun onIceConnectionReceivingChange(
                        receiving: Boolean
                    ) {
                    }

                    override fun onIceGatheringChange(
                        state: PeerConnection.IceGatheringState?
                    ) {

                        Log.d(
                            "WEBRTC",
                            "🌐 ICE gathering state: $state"
                        )
                    }

                    override fun onIceCandidatesRemoved(
                        candidates: Array<out IceCandidate>?
                    ) {
                    }

                    override fun onAddStream(
                        stream: MediaStream?
                    ) {
                    }

                    override fun onRemoveStream(
                        stream: MediaStream?
                    ) {
                    }

                    override fun onRenegotiationNeeded() {
                    }

                    override fun onAddTrack(
                        receiver: RtpReceiver?,
                        mediaStreams: Array<out MediaStream>?
                    ) {
                        val track =
                            receiver?.track()

                        if (track is AudioTrack) {
                            Log.d(
                                "AUDIO",
                                "🔊 AUDIO TRACK ADDED"
                            )
                        }
                    }
                }

            )!!

        /*
         * ============================================================
         * VIDEO RECEIVE ONLY
         * ============================================================
         */

        peerConnection?.addTransceiver(

            MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO,

            RtpTransceiver.RtpTransceiverInit(

                RtpTransceiver.RtpTransceiverDirection.RECV_ONLY
            )
        )

        // Start a fresh diagnostic session for this PeerConnection.
        resetDiagnostics()
        startVideoStatsLogging()

        return peerConnection!!
    }

    /*
     * ================================================================
     * VIDEO RECEIVE DIAGNOSTICS
     * ================================================================
     * Poll WebRTC receiver stats once per second. This does not change
     * media behaviour; it only tells us whether RTP packets continue
     * arriving and whether the H264 decoder continues producing frames.
     */

    private fun startVideoStatsLogging() {
        statsExecutor?.shutdownNow()

        statsExecutor = Executors.newSingleThreadScheduledExecutor()

        statsExecutor?.scheduleAtFixedRate(
            {
                collectVideoStats()
            },
            1,
            1,
            TimeUnit.SECONDS
        )

        // IMPORTANT:
        // Print a cumulative diagnostic snapshot every 5 seconds.
        // The app may be force-stopped/crashed, so close() is NOT a
        // reliable place for the only summary. This periodic snapshot
        // guarantees that the terminal always receives recent data.
        statsExecutor?.scheduleAtFixedRate(
            {
            },
            5,
            5,
            TimeUnit.SECONDS
        )
    }

    private fun collectVideoStats() {
        val pc = peerConnection ?: return

        pc.getStats(object : RTCStatsCollectorCallback {
            override fun onStatsDelivered(report: RTCStatsReport) {
                for (stat in report.getStatsMap().values) {
                    val values = stat.members

                    if (stat.type == "inbound-rtp") {
                        val mediaType = values["kind"] ?: values["mediaType"]

                        if (mediaType?.toString() == "video") {
                            val packetsReceived = statLong(values, "packetsReceived")
                            val packetsLost = statLong(values, "packetsLost")
                            val bytesReceived = statLong(values, "bytesReceived")
                            val framesReceived = statLong(values, "framesReceived")
                            val framesDecoded = statLong(values, "framesDecoded")
                            val jitter = statDouble(values, "jitter")
                            val decodeTime = statDouble(values, "totalDecodeTime")
                            val freezeCount = statLong(values, "freezeCount")
                            val freezesDuration = statDouble(values, "totalFreezesDuration")

                            if (jitter >= 0.0) diagnosticsMaxVideoJitter = maxOf(diagnosticsMaxVideoJitter, jitter)
                            if (decodeTime >= 0.0) diagnosticsMaxVideoDecodeTime = maxOf(diagnosticsMaxVideoDecodeTime, decodeTime)
                            if (freezeCount >= 0L) diagnosticsLastFreezeCount = freezeCount
                            if (freezesDuration >= 0.0) diagnosticsLastFreezeDuration = freezesDuration
                            diagnosticsLastVideoPackets = packetsReceived
                            diagnosticsLastVideoLost = packetsLost
                        }
                    }

                    if (stat.type == "inbound-rtp") {
                        val mediaType = values["kind"] ?: values["mediaType"]
                        if (mediaType?.toString() == "audio") {
                            val packets = statLong(values, "packetsReceived")
                            val lost = statLong(values, "packetsLost")
                            val bytes = statLong(values, "bytesReceived")

                            diagnosticsLastAudioPackets = packets
                            diagnosticsLastAudioLost = lost
                        }
                    }

                    if (stat.type == "candidate-pair") {
                        val state = values["state"]?.toString()
                        val nominated = values["nominated"]?.toString()?.toBoolean() ?: false
                        val rtt = statDouble(values, "currentRoundTripTime")

                        if (state == "succeeded" && nominated && rtt >= 0.0) {
                            diagnosticsRttSamplesMs.add(rtt * 1000.0)
                        }
                    }
                }
            }
        })
    }

    private fun resetDiagnostics() {
        diagnosticsRttSamplesMs.clear()
        diagnosticsStartedAtNs = System.nanoTime()
        diagnosticsLastVideoPackets = -1L
        diagnosticsLastVideoLost = -1L
        diagnosticsLastFreezeCount = -1L
        diagnosticsLastFreezeDuration = -1.0
        diagnosticsMaxVideoJitter = 0.0
        diagnosticsMaxVideoDecodeTime = 0.0
        diagnosticsLastVideoPackets = -1L
        diagnosticsLastVideoLost = -1L
        diagnosticsLastAudioPackets = -1L
        diagnosticsLastAudioLost = -1L
    }

    private fun statLong(
        values: Map<String, Any>,
        name: String
    ): Long {
        return when (val value = values[name]) {
            is Number -> value.toLong()
            else -> value?.toString()?.toDoubleOrNull()?.toLong() ?: -1L
        }
    }

    private fun statDouble(
        values: Map<String, Any>,
        name: String
    ): Double {
        return when (val value = values[name]) {
            is Number -> value.toDouble()
            else -> value?.toString()?.toDoubleOrNull() ?: -1.0
        }
    }

    private fun formatStat(value: Double): String {
        if (value < 0.0) return "-"
        return String.format(java.util.Locale.US, "%.4f", value)
    }

    /*
     * ================================================================
     * RECEIVE BINARY
     * ================================================================
     */

    /**
     * Begin Trusted Device enrollment from a scanned QR payload.
     * The QR contains only the one-time pairing invitation.
     */
    fun startTrustedPairing(qrPayload: String) {
        val pairing = com.example.lazypc.security.TrustedPairing(
            context,
            securityKeyStore,
        )

        trustedPairingInvitation = pairing.parseQrPayload(qrPayload)
        trustedPairingStarted = true

        Log.i(
            "LazyPC-Security",
            "Trusted Device pairing armed"
        )

        sendTrustedPairingHello()
    }

    private fun sendTrustedPairingHello() {
        if (!trustedPairingStarted) return

        val invitation = trustedPairingInvitation ?: return
        val channel = dataChannel ?: return

        if (channel.state() != DataChannel.State.OPEN) return

        val hello = JSONObject().apply {
            put("type", "pair_hello")
            put("version", 1)
            put("algorithm", "ECDSA-P256-HW-ATTESTATION")
            put("pairing_token", invitation.token)
        }

        if (sendText(hello.toString())) {
            Log.i(
                "LazyPC-Security",
                "PAIR_HELLO sent over WebRTC DataChannel"
            )
        }
    }

    private fun handleTrustedPairingChallenge(text: String): Boolean {
        if (!trustedPairingStarted) return false

        val json = try {
            JSONObject(text)
        } catch (_: Throwable) {
            return false
        }

        if (json.optString("type") != "pair_challenge") {
            return false
        }

        try {
            val invitation = requireNotNull(trustedPairingInvitation)
            val pairing = com.example.lazypc.security.TrustedPairing(
                context,
                securityKeyStore,
            )

            val response = pairing.createPairResponse(
                invitation,
                json,
            )

            require(sendText(response.toString())) {
                "Failed to send PAIR_RESPONSE"
            }

            trustedPairingStarted = false
            trustedPairingInvitation = null

            Log.i(
                "LazyPC-Security",
                "Trusted Device pairing response sent"
            )
        } catch (error: Throwable) {
            trustedPairingStarted = false
            trustedPairingInvitation = null

            Log.e(
                "LazyPC-Security",
                "Trusted Device pairing failed",
                error
            )
        }

        return true
    }

    private fun handleHardwareAuthMessage(text: String): Boolean {
        val json = try {
            JSONObject(text)
        } catch (_: Throwable) {
            return false
        }

        if (json.optString("type") != "hw_auth_challenge") {
            return false
        }

        if (hardwareAuthPending) {
            Log.w("LazyPC-Security", "Duplicate HW_AUTH_CHALLENGE ignored")
            return true
        }

        try {
            val version = json.optInt("version", -1)
            val algorithm = json.optString("algorithm")
            val sessionId = json.optString("session_id")
            val challengeB64 = json.optString("challenge")

            require(version == 1) { "Unsupported HW_AUTH version" }
            require(algorithm == "ECDSA-P256-HW-ATTESTATION") {
                "Unsupported HW_AUTH algorithm"
            }
            require(sessionId.isNotEmpty()) { "Missing HW_AUTH session_id" }
            require(challengeB64.isNotEmpty()) { "Missing HW_AUTH challenge" }

            // Verify that the challenge is valid Base64 before signing.
            val challenge = Base64.decode(challengeB64, Base64.DEFAULT)
            require(challenge.size == 32) { "Invalid HW_AUTH challenge length" }

            val keyInfo = securityKeyStore.getExistingWebRtcHardwareKey(context)

            val message = (
                    "LAZYPC_HW_AUTH_V1|SESSION|" +
                            sessionId + "|" +
                            challengeB64 + "|" +
                            keyInfo.publicKeyBase64
                    ).toByteArray(StandardCharsets.UTF_8)

            val signature = securityKeyStore.signHardwareProof(message)

            val response = JSONObject().apply {
                put("type", "hw_auth_response")
                put("version", 1)
                put("algorithm", "ECDSA-P256-HW-ATTESTATION")
                put("session_id", sessionId)
                put("challenge", challengeB64)
                put("hardware_public", keyInfo.publicKeyBase64)
                put("signature", signature)
                put(
                    "attestation_challenge",
                    keyInfo.attestationChallengeBase64
                )
                put(
                    "attestation_chain",
                    org.json.JSONArray(keyInfo.attestationChainBase64)
                )
            }

            hardwareAuthPending = true

            if (!sendText(response.toString())) {
                hardwareAuthPending = false
                throw IllegalStateException("Failed to send HW_AUTH_RESPONSE")
            }

            Log.i(
                "LazyPC-Security",
                "HW_AUTH_RESPONSE sent from Android Keystore hardware key"
            )

        } catch (error: Throwable) {
            hardwareAuthPending = false
            hardwareAuthorized = false
            Log.e(
                "LazyPC-Security",
                "HW_AUTH failed",
                error
            )
        }

        return true
    }

    private fun handleBinaryMessage(
        bytes: ByteArray
    ) {

        if (bytes.isEmpty()) {
            return
        }

        val packetType =
            bytes[0]
                .toInt()
                .and(0xFF)

        when (packetType) {

            PACKET_CURSOR_POSITION -> {

                /*
                 * Packet:
                 *
                 * 1 byte  packet type
                 * 4 bytes normalized X
                 * 4 bytes normalized Y
                 *
                 * Total: 9 bytes
                 */

                if (bytes.size != 9) {

                    Log.w(
                        "CURSOR",
                        "Invalid cursor packet size: ${bytes.size}"
                    )

                    return
                }

                val byteBuffer =
                    ByteBuffer
                        .wrap(
                            bytes,
                            1,
                            8
                        )
                        .order(
                            ByteOrder.BIG_ENDIAN
                        )

                val normalizedX =
                    byteBuffer.float

                val normalizedY =
                    byteBuffer.float

                onCursorPosition(
                    normalizedX,
                    normalizedY
                )
            }

            else -> {

                Log.v(
                    "DATA",
                    "Unknown binary packet: 0x${packetType.toString(16)}"
                )
            }
        }
    }

    fun addRemoteCandidate(
        candidate: IceCandidate
    ) {

        Log.d(
            "WEBRTC",
            "📥 Remote ICE candidate received"
        )

        peerConnection?.addIceCandidate(
            candidate
        )
    }

    fun setRemoteOffer(
        sdp: String,
        onAnswer: (String) -> Unit
    ) {

        val pc =
            peerConnection ?: return

        val offer =
            SessionDescription(

                SessionDescription.Type.OFFER,

                sdp
            )

        Log.d(
            "SDP",
            "📥 Remote offer received"
        )

        pc.setRemoteDescription(

            object : SdpObserver {

                override fun onSetSuccess() {

                    Log.d(
                        "WEBRTC",
                        "✅ Remote SDP applied"
                    )

                    pc.createAnswer(

                        object : SdpObserver {

                            override fun onCreateSuccess(
                                answer: SessionDescription
                            ) {

                                Log.d(
                                    "SDP",
                                    "📤 Local answer created"
                                )

                                pc.setLocalDescription(

                                    object : SdpObserver {

                                        override fun onSetSuccess() {

                                            Log.d(
                                                "WEBRTC",
                                                "✅ Local SDP applied"
                                            )

                                            onAnswer(
                                                answer.description
                                            )
                                        }

                                        override fun onSetFailure(
                                            error: String?
                                        ) {

                                            Log.e(
                                                "WEBRTC",
                                                "LOCAL SDP ERROR: $error"
                                            )
                                        }

                                        override fun onCreateSuccess(
                                            description: SessionDescription?
                                        ) {
                                        }

                                        override fun onCreateFailure(
                                            error: String?
                                        ) {
                                        }

                                    },

                                    answer
                                )
                            }

                            override fun onSetSuccess() {
                            }

                            override fun onSetFailure(
                                error: String?
                            ) {

                                Log.e(
                                    "WEBRTC",
                                    "ANSWER ERROR: $error"
                                )
                            }

                            override fun onCreateFailure(
                                error: String?
                            ) {

                                Log.e(
                                    "WEBRTC",
                                    "CREATE ANSWER ERROR: $error"
                                )
                            }

                        },

                        MediaConstraints()
                    )
                }

                override fun onSetFailure(
                    error: String?
                ) {

                    Log.e(
                        "WEBRTC",
                        "❌ SET REMOTE FAILED: $error"
                    )
                }

                override fun onCreateSuccess(
                    description: SessionDescription?
                ) {
                }

                override fun onCreateFailure(
                    error: String?
                ) {
                }

            },

            offer
        )
    }

    fun close(sendSessionClose: Boolean = true) {
        Log.d("WEBRTC", "Closing WebRTC client")

        // Tell Windows explicitly when this side is intentionally ending the
        // session. Network loss / process kill cannot send this message, so
        // Windows will keep the session alive until its transport timeout.
        if (sendSessionClose) {
            sendText(SESSION_CLOSE)
        }

        statsExecutor?.shutdownNow()
        statsExecutor = null
        trustedPairingStarted = false
        trustedPairingInvitation = null
        diagnosticsStartedAtNs = 0L

        clearAudioRoute()

        dataChannel?.close()
        dataChannel = null

        peerConnection?.close()
        peerConnection = null

        audioDeviceModule?.release()
        audioDeviceModule = null

        Log.d("WEBRTC", "WebRTC client closed")
    }

    /*
     * ================================================================
     * SEND BINARY THROUGH DATACHANNEL
     * ================================================================
     */

    fun sendBinary(
        data: ByteArray
    ): Boolean {

        val channel = dataChannel

        if (channel == null) {

            Log.w(
                "DATA",
                "⚠️ TX BINARY SKIPPED: DataChannel is null"
            )

            return false
        }

        if (channel.state() != DataChannel.State.OPEN) {

            Log.w(
                "DATA",
                "⚠️ TX BINARY SKIPPED: state=${channel.state()}"
            )

            return false
        }

        val buffer =
            DataChannel.Buffer(

                ByteBuffer.wrap(data),

                true
            )

        val result =
            channel.send(buffer)

        if (!result) {

            Log.e(
                "DATA",
                "❌ TX BINARY FAILED: ${data.size} bytes"
            )
        }

        return result
    }

    /*
     * ================================================================
     * SEND TEXT
     * ================================================================
     */

    fun sendText(
        text: String
    ): Boolean {

        val channel =
            dataChannel ?: return false

        if (
            channel.state() != DataChannel.State.OPEN
        ) {

            return false
        }

        val buffer =
            DataChannel.Buffer(

                ByteBuffer.wrap(
                    text.toByteArray()
                ),

                false
            )

        return channel.send(
            buffer
        )
    }

    /*
     * ================================================================
     * TEST PING
     * ================================================================
     */

    fun sendPing() {

        val result =
            sendText(
                "PING"
            )

        if (result) {

            Log.d(
                "DATA",
                "📤 TX = PING"
            )
        }
    }
}