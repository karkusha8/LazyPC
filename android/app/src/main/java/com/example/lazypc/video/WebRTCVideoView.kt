package com.example.lazypc.video

import android.content.Context
import org.webrtc.SurfaceViewRenderer
import org.webrtc.EglBase
import org.webrtc.VideoTrack

class WebRTCVideoView(context: Context) : SurfaceViewRenderer(context) {

    private val eglBase = EglBase.create()

    init {
        init(eglBase.eglBaseContext, null)
        setEnableHardwareScaler(true)
    }

    fun attachTrack(track: VideoTrack) {
        track.addSink(this)
    }
}