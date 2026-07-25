package com.example.lazypc.webrtc

import android.content.Context
import android.util.Log
import org.webrtc.*
import java.nio.ByteBuffer
import java.nio.ByteOrder


class WebRTCClient(

    private val context: Context,

    private val eglContext: EglBase.Context,

    private val onFrame: (VideoTrack) -> Unit,

    private val onIce: (IceCandidate) -> Unit,

    private val onCursorPosition: (Float, Float) -> Unit

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


    fun init() {

        val options =
            PeerConnectionFactory.InitializationOptions
                .builder(context)
                .createInitializationOptions()


        PeerConnectionFactory.initialize(
            options
        )


        factory =
            PeerConnectionFactory
                .builder()

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
                                "🎬 TRACK RECEIVED"
                            )

                            onFrame(track)
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


        return peerConnection!!
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