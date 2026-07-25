package com.example.lazypc.webrtc

import org.webrtc.*

class WebRTCObserver(
    private val onTrack: (VideoTrack) -> Unit
) : PeerConnection.Observer {

    override fun onTrack(transceiver: RtpTransceiver?) {
        val track = transceiver?.receiver?.track() as? VideoTrack
        track?.let { onTrack(it) }
    }

    override fun onIceCandidate(candidate: IceCandidate?) {}
    override fun onConnectionChange(newState: PeerConnection.PeerConnectionState?) {
        println("🔗 state: $newState")
    }

    // остальные пустые
    override fun onSignalingChange(p0: PeerConnection.SignalingState?) {}
    override fun onIceConnectionChange(p0: PeerConnection.IceConnectionState?) {}
    override fun onIceConnectionReceivingChange(p0: Boolean) {}
    override fun onIceGatheringChange(p0: PeerConnection.IceGatheringState?) {}
    override fun onIceCandidatesRemoved(p0: Array<out IceCandidate>?) {}
    override fun onAddStream(p0: MediaStream?) {}
    override fun onRemoveStream(p0: MediaStream?) {}
    override fun onDataChannel(p0: DataChannel?) {}
    override fun onRenegotiationNeeded() {}
    override fun onAddTrack(p0: RtpReceiver?, p1: Array<out MediaStream>?) {}
}