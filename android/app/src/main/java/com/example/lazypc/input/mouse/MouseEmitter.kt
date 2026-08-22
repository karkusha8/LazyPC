package com.example.lazypc.input.mouse

import com.example.lazypc.webrtc.WebRTCClient
import java.nio.ByteBuffer
import java.nio.ByteOrder


class MouseEmitter(

    private val webrtc: WebRTCClient

) {


    companion object {

        private const val PACKET_TAP = 0x40

        private const val PACKET_DOUBLE_TAP = 0x41

        private const val PACKET_DRAG_START = 0x42

        private const val PACKET_DRAG_MOVE = 0x43

        private const val PACKET_DRAG_END = 0x44

        private const val PACKET_MOVE = 0x45

        private const val PACKET_RIGHT_CLICK = 0x46

        private const val PACKET_SCROLL = 0x47
    }


    /*
     * ================================================================
     * MOVE
     * ================================================================
     */


    fun sendMove(
        dx: Float,
        dy: Float
    ) {

        val payload =

            ByteBuffer
                .allocate(8)

                .order(
                    ByteOrder.BIG_ENDIAN
                )

                .putFloat(dx)

                .putFloat(dy)

                .array()


        sendPacket(
            PACKET_MOVE,
            payload
        )
    }


    /*
     * ================================================================
     * TAP
     * ================================================================
     */


    fun sendTap() {

        sendPacket(

            PACKET_TAP,

            ByteArray(0)
        )
    }


    /*
     * ================================================================
     * RIGHT CLICK
     * ================================================================
     */


    fun sendRightClick() {

        sendPacket(

            PACKET_RIGHT_CLICK,

            ByteArray(0)
        )
    }


    /*
     * ================================================================
     * DOUBLE TAP
     * ================================================================
     */


    fun sendDoubleTap() {

        sendPacket(

            PACKET_DOUBLE_TAP,

            ByteArray(0)
        )
    }


    /*
     * ================================================================
     * SCROLL
     * ================================================================
     */


    fun sendScroll(
        dy: Float
    ) {

        val payload =

            ByteBuffer
                .allocate(4)

                .order(
                    ByteOrder.BIG_ENDIAN
                )

                .putFloat(dy)

                .array()


        sendPacket(

            PACKET_SCROLL,

            payload
        )
    }


    /*
     * ================================================================
     * DRAG START
     * ================================================================
     */


    fun sendDragStart() {

        sendPacket(

            PACKET_DRAG_START,

            ByteArray(0)
        )
    }


    /*
     * ================================================================
     * DRAG MOVE
     * ================================================================
     */


    fun sendDragMove(
        dx: Float,
        dy: Float
    ) {

        val payload =

            ByteBuffer
                .allocate(8)

                .order(
                    ByteOrder.BIG_ENDIAN
                )

                .putFloat(dx)

                .putFloat(dy)

                .array()


        sendPacket(

            PACKET_DRAG_MOVE,

            payload
        )
    }


    /*
     * ================================================================
     * DRAG END
     * ================================================================
     */


    fun sendDragEnd() {

        sendPacket(

            PACKET_DRAG_END,

            ByteArray(0)
        )
    }


    /*
     * ================================================================
     * PACKET
     * ================================================================
     */


    private fun sendPacket(
        type: Int,
        payload: ByteArray
    ) {

        val buffer =
            ByteBuffer
                .allocate(
                    1 + payload.size
                )

                .order(
                    ByteOrder.BIG_ENDIAN
                )

                .put(
                    type.toByte()
                )

                .put(
                    payload
                )

        webrtc.sendBinary(
            buffer.array()
        )
    }
}