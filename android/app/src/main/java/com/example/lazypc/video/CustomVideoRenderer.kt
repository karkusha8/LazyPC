package com.example.lazypc.video

import android.content.Context
import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.view.Surface
import android.view.TextureView
import org.webrtc.EglBase
import org.webrtc.EglRenderer
import org.webrtc.GlRectDrawer
import org.webrtc.VideoFrame
import org.webrtc.VideoSink

/**
 * Custom WebRTC renderer based on TextureView.
 *
 * TextureView stays inside the normal Android view hierarchy, so its parent
 * can be clipped, scaled and translated normally. WebRTC still handles RTP,
 * decoding and VideoFrame creation; this class only renders those frames.
 */
class CustomVideoRenderer(
    context: Context
) : TextureView(context), VideoSink {

    private val eglRenderer =
        EglRenderer("LazyPC-CustomTextureRenderer")

    private var initialized = false
    private var surfaceTextureAvailable = false
    private var currentSurface: Surface? = null

    init {
        isOpaque = true

        surfaceTextureListener =
            object : SurfaceTextureListener {

                override fun onSurfaceTextureAvailable(
                    surface: SurfaceTexture,
                    width: Int,
                    height: Int
                ) {
                    surfaceTextureAvailable = true
                    createEglSurface(surface)
                }

                override fun onSurfaceTextureSizeChanged(
                    surface: SurfaceTexture,
                    width: Int,
                    height: Int
                ) {
                    if (surfaceTextureAvailable) {
                        createEglSurface(surface)
                    }
                }

                override fun onSurfaceTextureDestroyed(
                    surface: SurfaceTexture
                ): Boolean {
                    surfaceTextureAvailable = false
                    releaseEglSurface()
                    return true
                }

                override fun onSurfaceTextureUpdated(
                    surface: SurfaceTexture
                ) = Unit
            }
    }

    fun initRenderer(
        sharedEglContext: EglBase.Context
    ) {
        if (initialized) return

        eglRenderer.init(
            sharedEglContext,
            EglBase.CONFIG_PLAIN,
            GlRectDrawer()
        )

        initialized = true

        if (surfaceTextureAvailable) {
            surfaceTexture?.let(::createEglSurface)
        }
    }

    private fun createEglSurface(
        texture: SurfaceTexture
    ) {
        if (!initialized) return

        if (currentSurface != null) {
            releaseEglSurface()
        }

        val surface = Surface(texture)
        currentSurface = surface

        eglRenderer.createEglSurface(surface)
    }

    private fun releaseEglSurface() {
        val oldSurface = currentSurface
        currentSurface = null

        if (oldSurface == null) return

        eglRenderer.releaseEglSurface {
            oldSurface.release()
        }
    }

    override fun onFrame(frame: VideoFrame) {
        if (!initialized) return
        eglRenderer.onFrame(frame)
    }

    /**
     * Applies zoom and pan to the rendered TextureView content.
     *
     * The TextureView itself keeps its layout size. Only its visual
     * transform changes, so the parent viewport can remain fixed.
     */
    /**
     * Transform only the visual contents of the TextureView.
     *
     * The parent fixed video window is clipped separately, so the
     * transformed content cannot enlarge the visible outer box.
     */
    fun setContentTransform(
        scale: Float,
        offsetX: Float,
        offsetY: Float
    ) {
        if (!scale.isFinite() || scale <= 0f) return
        if (!offsetX.isFinite() || !offsetY.isFinite()) return

        val viewWidth = width.toFloat()
        val viewHeight = height.toFloat()

        if (viewWidth <= 0f || viewHeight <= 0f) return

        val matrix = Matrix()

        matrix.setScale(
            scale,
            scale,
            viewWidth / 2f,
            viewHeight / 2f
        )

        matrix.postTranslate(
            offsetX,
            offsetY
        )

        setTransform(matrix)
    }

    fun resetContentTransform() {
        setTransform(null)
    }

    fun releaseRenderer() {
        if (!initialized) return

        initialized = false
        surfaceTextureAvailable = false

        val oldSurface = currentSurface
        currentSurface = null

        if (oldSurface != null) {
            eglRenderer.releaseEglSurface {
                oldSurface.release()
                eglRenderer.release()
            }
        } else {
            eglRenderer.release()
        }
    }
}