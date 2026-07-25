package com.example.lazypc

import android.view.ViewGroup
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.viewinterop.AndroidView
import org.webrtc.EglBase
import org.webrtc.RendererCommon
import org.webrtc.SurfaceViewRenderer


@Composable
fun ScreenSurfaceView(

    modifier: Modifier = Modifier,

    eglContext: EglBase.Context,

    onSurfaceReady: (SurfaceViewRenderer) -> Unit,

    scalingType: RendererCommon.ScalingType =
        RendererCommon.ScalingType.SCALE_ASPECT_FIT

) {

    Box(

        modifier = modifier
            .background(Color.Black),

        contentAlignment = Alignment.Center

    ) {

        AndroidView(

            modifier = Modifier.matchParentSize(),

            factory = { context ->

                SurfaceViewRenderer(context).apply {

                    layoutParams =
                        ViewGroup.LayoutParams(

                            ViewGroup.LayoutParams.MATCH_PARENT,

                            ViewGroup.LayoutParams.MATCH_PARENT
                        )


                    init(
                        eglContext,
                        null
                    )


                    setEnableHardwareScaler(true)


                    setScalingType(
                        scalingType
                    )


                    setMirror(false)


                    setZOrderMediaOverlay(false)


                    setZOrderOnTop(false)


                    onSurfaceReady(this)
                }
            },

            update = { renderer ->

                renderer.setScalingType(
                    scalingType
                )
            }
        )
    }
}