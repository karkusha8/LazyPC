package com.example.lazypc.webrtc

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.os.Build
import android.util.Log
import org.webrtc.*
import org.webrtc.audio.JavaAudioDeviceModule
import java.nio.ByteBuffer
import java.nio.ByteOrder
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

    companion object {

        private const val PACKET_CURSOR_POSITION =
            0x60
    }


    private lateinit var factory:
            PeerConnectionFactory


    private var peerConnection:
            PeerConnection? = null


    private var dataChannel:
            DataChannel? = null

    private var statsExecutor: ScheduledExecutorService? = null

    private var statsLastPacketsReceived = -1L
    private var statsLastBytesReceived = -1L
    private var statsLastFramesReceived = -1L
    private var statsLastFramesDecoded = -1L

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
                                "📤 LOCAL ICE: ${it.sdp}"
                            )

                            onIce(it)
                        }
                    }


                    override fun onIceConnectionChange(
                        state: PeerConnection.IceConnectionState?
                    ) {

                        Log.d(
                            "WEBRTC",
                            "🧊 ICE STATE: $state"
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
                            "🌐 GATHERING: $state"
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
                printDiagnosticsSummary(periodic = true)
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
                var foundInboundVideo = false

                for (stat in report.getStatsMap().values) {
                    val values = stat.members

                    if (stat.type == "inbound-rtp") {
                        val mediaType = values["kind"] ?: values["mediaType"]

                        if (mediaType?.toString() == "video") {
                            foundInboundVideo = true

                            val packetsReceived = statLong(values, "packetsReceived")
                            val packetsLost = statLong(values, "packetsLost")
                            val bytesReceived = statLong(values, "bytesReceived")
                            val framesReceived = statLong(values, "framesReceived")
                            val framesDecoded = statLong(values, "framesDecoded")
                            val framesDropped = statLong(values, "framesDropped")
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

                            Log.d(
                                "VIDEO_STATS",
                                "[VIDEO][IN] " +
                                        "packets=$packetsReceived " +
                                        "lost=$packetsLost " +
                                        "bytes=$bytesReceived " +
                                        "framesRx=$framesReceived " +
                                        "framesDecoded=$framesDecoded " +
                                        "dropped=$framesDropped " +
                                        "jitter=${formatStat(jitter)} " +
                                        "decodeTime=${formatStat(decodeTime)} " +
                                        "freezeCount=$freezeCount " +
                                        "freezeDuration=${formatStat(freezesDuration)} " +
                                        "dPackets=${delta(statsLastPacketsReceived, packetsReceived)} " +
                                        "dFramesRx=${delta(statsLastFramesReceived, framesReceived)} " +
                                        "dDecoded=${delta(statsLastFramesDecoded, framesDecoded)} " +
                                        "dBytes=${delta(statsLastBytesReceived, bytesReceived)}"
                            )

                            statsLastPacketsReceived = packetsReceived
                            statsLastBytesReceived = bytesReceived
                            statsLastFramesReceived = framesReceived
                            statsLastFramesDecoded = framesDecoded
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

                            Log.d(
                                "AUDIO_STATS",
                                "[AUDIO][IN] packets=$packets lost=$lost bytes=$bytes " +
                                        "dPackets=${delta(statsLastAudioPacketsForLog, packets)} " +
                                        "dLost=${delta(statsLastAudioLostForLog, lost)}"
                            )

                            statsLastAudioPacketsForLog = packets
                            statsLastAudioLostForLog = lost
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

                if (!foundInboundVideo) {
                    Log.w(
                        "VIDEO_STATS",
                        "[VIDEO][IN] No inbound video RTP stats found"
                    )
                }
            }
        })
    }

    private var statsLastAudioPacketsForLog = -1L
    private var statsLastAudioLostForLog = -1L

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
        statsLastAudioPacketsForLog = -1L
        statsLastAudioLostForLog = -1L
    }

    /*
     * ================================================================
     * SESSION DIAGNOSTICS SUMMARY
     * ================================================================
     *
     * Diagnostics only. This does not change media behaviour.
     *
     * Logcat filter:
     *
     *     tag:LAZYPC_DIAG
     *
     * The average is the real arithmetic mean:
     *
     *     sum(all samples) / number of samples
     *
     * It is NOT (min + max) / 2.
     */
    private fun printDiagnosticsSummary(periodic: Boolean = false) {
        val started = diagnosticsStartedAtNs
        if (started <= 0L) return

        val durationSec =
            (System.nanoTime() - started).coerceAtLeast(0L) / 1_000_000_000.0

        Log.d("LAZYPC_DIAG", "================================================================================")
        Log.d(
            "LAZYPC_DIAG",
            if (periodic) {
                "[DIAG][SNAPSHOT] SESSION DIAGNOSTICS (every 5s)"
            } else {
                "[DIAG][SUMMARY] SESSION DIAGNOSTICS"
            }
        )
        Log.d("LAZYPC_DIAG", "================================================================================")
        Log.d(
            "LAZYPC_DIAG",
            "[DIAG][SUMMARY] duration=${String.format(java.util.Locale.US, "%.1f", durationSec)}s"
        )

        Log.d(
            "LAZYPC_DIAG",
            "[DIAG][SUMMARY] RTT statistics (real arithmetic mean):"
        )

        if (diagnosticsRttSamplesMs.isEmpty()) {
            Log.d("LAZYPC_DIAG", "[DIAG][RTT] network: no samples")
        } else {
            val min = diagnosticsRttSamplesMs.minOrNull() ?: 0.0
            val max = diagnosticsRttSamplesMs.maxOrNull() ?: 0.0
            val avg = diagnosticsRttSamplesMs.sum() / diagnosticsRttSamplesMs.size.toDouble()

            Log.d(
                "LAZYPC_DIAG",
                "[DIAG][RTT] network: " +
                        "min=${formatMs(min)} " +
                        "avg=${formatMs(avg)} " +
                        "max=${formatMs(max)} " +
                        "samples=${diagnosticsRttSamplesMs.size}"
            )
        }

        val videoLossText =
            if (diagnosticsLastVideoPackets >= 0L && diagnosticsLastVideoLost >= 0L) {
                val total = diagnosticsLastVideoPackets + diagnosticsLastVideoLost
                if (total > 0L) {
                    String.format(
                        java.util.Locale.US,
                        "%.2f%%",
                        diagnosticsLastVideoLost * 100.0 / total.toDouble()
                    )
                } else {
                    "0.00%"
                }
            } else {
                "-"
            }

        val audioLossText =
            if (diagnosticsLastAudioPackets >= 0L && diagnosticsLastAudioLost >= 0L) {
                val total = diagnosticsLastAudioPackets + diagnosticsLastAudioLost
                if (total > 0L) {
                    String.format(
                        java.util.Locale.US,
                        "%.2f%%",
                        diagnosticsLastAudioLost * 100.0 / total.toDouble()
                    )
                } else {
                    "0.00%"
                }
            } else {
                "-"
            }

        Log.d(
            "LAZYPC_DIAG",
            "[DIAG][VIDEO] " +
                    "freezes=${if (diagnosticsLastFreezeCount >= 0L) diagnosticsLastFreezeCount else "-"} " +
                    "freezeDuration=${if (diagnosticsLastFreezeDuration >= 0.0) formatSeconds(diagnosticsLastFreezeDuration) else "-"} " +
                    "packetLoss=$videoLossText " +
                    "maxJitter=${formatStat(diagnosticsMaxVideoJitter)} " +
                    "maxDecodeTime=${formatSeconds(diagnosticsMaxVideoDecodeTime)}"
        )

        Log.d(
            "LAZYPC_DIAG",
            "[DIAG][AUDIO] " +
                    "packets=${if (diagnosticsLastAudioPackets >= 0L) diagnosticsLastAudioPackets else "-"} " +
                    "lost=${if (diagnosticsLastAudioLost >= 0L) diagnosticsLastAudioLost else "-"} " +
                    "packetLoss=$audioLossText"
        )

        Log.d(
            "LAZYPC_DIAG",
            "[DIAG][VIDEO_RENDER] frame-gap/fps summary is printed by CustomVideoRenderer"
        )

        Log.d("LAZYPC_DIAG", "================================================================================")
        Log.d("LAZYPC_DIAG", "[DIAG][SUMMARY] END")
        Log.d("LAZYPC_DIAG", "================================================================================")
    }

    private fun formatMs(value: Double): String =
        String.format(java.util.Locale.US, "%.1fms", value)

    private fun formatSeconds(value: Double): String =
        String.format(java.util.Locale.US, "%.3fs", value)

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

    private fun delta(previous: Long, current: Long): Long {
        if (previous < 0L || current < 0L) return -1L
        return current - previous
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
            "📥 ADD REMOTE ICE: ${candidate.sdp}"
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
            "================ OFFER ================"
        )

        Log.d(
            "SDP",
            sdp
        )

        Log.d(
            "SDP",
            "======================================="
        )


        pc.setRemoteDescription(

            object : SdpObserver {


                override fun onSetSuccess() {


                    Log.d(
                        "WEBRTC",
                        "✅ REMOTE SDP SET"
                    )


                    pc.createAnswer(

                        object : SdpObserver {


                            override fun onCreateSuccess(
                                answer: SessionDescription
                            ) {


                                Log.d(
                                    "SDP",
                                    "================ ANSWER ================"
                                )

                                Log.d(
                                    "SDP",
                                    answer.description
                                )

                                Log.d(
                                    "SDP",
                                    "========================================"
                                )


                                pc.setLocalDescription(

                                    object : SdpObserver {


                                        override fun onSetSuccess() {

                                            Log.d(
                                                "WEBRTC",
                                                "✅ LOCAL SDP SET"
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


    fun close() {
        Log.d("WEBRTC", "Closing WebRTC client")

        printDiagnosticsSummary()

        statsExecutor?.shutdownNow()
        statsExecutor = null
        statsLastPacketsReceived = -1L
        statsLastBytesReceived = -1L
        statsLastFramesReceived = -1L
        statsLastFramesDecoded = -1L
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