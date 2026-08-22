package com.example.lazypc.video

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.setValue
import kotlin.math.max

class ScreenViewport {
    var videoWidth by mutableFloatStateOf(0f)
        private set
    var videoHeight by mutableFloatStateOf(0f)
        private set
    var viewportWidth by mutableFloatStateOf(0f)
        private set
    var viewportHeight by mutableFloatStateOf(0f)
        private set
    var scale by mutableFloatStateOf(1f)
        private set
    var offsetX by mutableFloatStateOf(0f)
        private set
    var offsetY by mutableFloatStateOf(0f)
        private set

    val fittedWidth: Float
        get() {
            if (videoWidth <= 0f || videoHeight <= 0f || viewportWidth <= 0f || viewportHeight <= 0f) return 0f
            val fitScale = minOf(viewportWidth / videoWidth, viewportHeight / videoHeight)
            return videoWidth * fitScale
        }

    val fittedHeight: Float
        get() {
            if (videoWidth <= 0f || videoHeight <= 0f || viewportWidth <= 0f || viewportHeight <= 0f) return 0f
            val fitScale = minOf(viewportWidth / videoWidth, viewportHeight / videoHeight)
            return videoHeight * fitScale
        }

    val contentWidth: Float get() = fittedWidth * scale
    val contentHeight: Float get() = fittedHeight * scale

    fun setVideoSize(width: Float, height: Float) {
        if (!width.isFinite() || !height.isFinite() || width <= 0f || height <= 0f) return
        videoWidth = width
        videoHeight = height
        clamp()
    }

    fun setViewportSize(width: Float, height: Float) {
        if (!width.isFinite() || !height.isFinite() || width <= 0f || height <= 0f) return
        viewportWidth = width
        viewportHeight = height
        clamp()
    }

    fun zoomAt(factor: Float, focusX: Float, focusY: Float) {
        if (!factor.isFinite() || factor <= 0f) return
        if (viewportWidth <= 0f || viewportHeight <= 0f) return
        val oldScale = scale
        val newScale = (oldScale * factor).coerceIn(MIN_SCALE, MAX_SCALE)
        if (!newScale.isFinite() || newScale == oldScale) return
        val ratio = newScale / oldScale
        val fromCenterX = focusX - viewportWidth / 2f
        val fromCenterY = focusY - viewportHeight / 2f
        offsetX = offsetX * ratio + fromCenterX * (1f - ratio)
        offsetY = offsetY * ratio + fromCenterY * (1f - ratio)
        scale = newScale
        clamp()
    }

    fun panBy(dx: Float, dy: Float) {
        if (!dx.isFinite() || !dy.isFinite()) return
        offsetX += dx
        offsetY += dy
        clamp()
    }

    fun updateScale(value: Float) {
        if (!value.isFinite()) return
        scale = value.coerceIn(MIN_SCALE, MAX_SCALE)
        clamp()
    }

    fun reset() {
        scale = 1f
        offsetX = 0f
        offsetY = 0f
    }

    fun clamp() {
        if (viewportWidth <= 0f || viewportHeight <= 0f || !viewportWidth.isFinite() || !viewportHeight.isFinite()) {
            offsetX = 0f
            offsetY = 0f
            return
        }
        val width = contentWidth
        val height = contentHeight
        if (!width.isFinite() || !height.isFinite()) {
            offsetX = 0f
            offsetY = 0f
            return
        }
        // Pan limits belong to the FIXED VIDEO BOX, not the outer
        // touch/screen viewport. The outer viewport is used to calculate
        // the fitted video size, but the transformed content is clipped
        // by the fitted video Box in RootScreen.
        val boxWidth = fittedWidth
        val boxHeight = fittedHeight

        val maxOffsetX = max(0f, (width - boxWidth) / 2f)
        val maxOffsetY = max(0f, (height - boxHeight) / 2f)
        offsetX = if (offsetX.isFinite()) offsetX.coerceIn(-maxOffsetX, maxOffsetX) else 0f
        offsetY = if (offsetY.isFinite()) offsetY.coerceIn(-maxOffsetY, maxOffsetY) else 0f
    }

    companion object {
        const val MIN_SCALE = 1f
        const val MAX_SCALE = 5f
    }
}