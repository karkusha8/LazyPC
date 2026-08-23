package com.example.lazypc.video

import android.content.Context
import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.os.SystemClock
import android.util.Log
import android.view.Surface
import android.view.TextureView
import org.webrtc.EglBase
import org.webrtc.EglRenderer
import org.webrtc.GlRectDrawer
import org.webrtc.VideoFrame
import org.webrtc.VideoSink
import java.util.Locale
import kotlin.math.max

/**
 * Custom WebRTC renderer with additional diagnostics.
 *
 * Purpose of this version:
 * - detect gaps between decoded VideoFrame callbacks;
 * - measure frame callback FPS;
 * - detect long pauses in the renderer callback path;
 * - detect SurfaceTexture lifecycle changes;
 * - periodically print a compact session summary.
 *
 * It does NOT intentionally change the video pipeline or buffering.
 */
class CustomVideoRenderer(
    context: Context
) : TextureView(context), VideoSink {

    private val eglRenderer =
        EglRenderer("LazyPC-CustomTextureRenderer")

    private var initialized = false
    private var surfaceTextureAvailable = false
    private var currentSurface: Surface? = null

    // Diagnostics
    private var frameCount = 0L
    private var sessionStartMs = 0L
    private var lastFrameMs = 0L

    private var maxGapMs = 0L
    private var gapCount = 0L

    private var maxCallbackMs = 0L
    private var slowCallbackCount = 0L

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

                    Log.d(
                        TAG,
                        "[SURFACE] available ${width}x${height}"
                    )

                    createEglSurface(surface)
                }

                override fun onSurfaceTextureSizeChanged(
                    surface: SurfaceTexture,
                    width: Int,
                    height: Int
                ) {
                    Log.d(
                        TAG,
                        "[SURFACE] size changed ${width}x${height}"
                    )

                    if (surfaceTextureAvailable) {
                        createEglSurface(surface)
                    }
                }

                override fun onSurfaceTextureDestroyed(
                    surface: SurfaceTexture
                ): Boolean {
                    Log.w(
                        TAG,
                        "[SURFACE] DESTROYED"
                    )

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

        sessionStartMs = SystemClock.elapsedRealtime()
        lastFrameMs = 0L

        Log.d(TAG, "[INIT] renderer initialized")

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

        Log.d(TAG, "[SURFACE] EGL surface created")

        eglRenderer.createEglSurface(surface)
    }

    private fun releaseEglSurface() {
        val oldSurface = currentSurface
        currentSurface = null

        if (oldSurface == null) return

        Log.d(TAG, "[SURFACE] EGL surface released")

        eglRenderer.releaseEglSurface {
            oldSurface.release()
        }
    }

    override fun onFrame(frame: VideoFrame) {
        if (!initialized) return

        val now = SystemClock.elapsedRealtime()

        if (lastFrameMs != 0L) {
            val gap = now - lastFrameMs

            maxGapMs = max(maxGapMs, gap)

            // At 60 FPS normal interval is about 16-17 ms.
            // >100 ms = visible interruption.
            // >500 ms = strong freeze candidate.
            if (gap >= 100L) {
                gapCount++

                val severity =
                    when {
                        gap >= 1000L -> "FREEZE"
                        gap >= 500L -> "LONG_GAP"
                        else -> "GAP"
                    }

                Log.w(
                    TAG,
                    "[$severity] frame gap=${gap}ms " +
                            "frame=$frameCount " +
                            "initialized=$initialized " +
                            "surface=$surfaceTextureAvailable"
                )
            }
        }

        frameCount++

        // We deliberately keep this callback timing measurement tiny.
        // It measures how long this method itself takes, not decoder time.
        val callbackStart = SystemClock.elapsedRealtimeNanos()

        eglRenderer.onFrame(frame)

        val callbackMs =
            (SystemClock.elapsedRealtimeNanos() - callbackStart) / 1_000_000L

        maxCallbackMs = max(maxCallbackMs, callbackMs)

        if (callbackMs >= 20L) {
            slowCallbackCount++

            Log.w(
                TAG,
                "[RENDER][SLOW] callback=${callbackMs}ms " +
                        "frame=$frameCount"
            )
        }

        lastFrameMs = now

    }

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

        // Machine-friendly renderer summary. It uses the DIAG tag so the
        // complete session can be found with a single Logcat filter: DIAG.
        Log.d(
            "DIAG",
            String.format(
                Locale.US,
                "[DIAG][VIDEO_RENDER] frames=%d maxGap=%dms maxCallback=%dms " +
                        "gaps=%d slowCallbacks=%d uptime=%.1fs",
                frameCount,
                maxGapMs,
                maxCallbackMs,
                gapCount,
                slowCallbackCount,
                if (sessionStartMs > 0L) {
                    (SystemClock.elapsedRealtime() - sessionStartMs).coerceAtLeast(0L) / 1000.0
                } else {
                    0.0
                }
            )
        )

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

    companion object {
        private const val TAG = "VIDEO"
    }
}