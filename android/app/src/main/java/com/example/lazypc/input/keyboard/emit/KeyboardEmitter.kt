package com.example.lazypc.input.keyboard.emit

import android.util.Log
import com.example.lazypc.input.keyboard.core.KeyAction
import com.example.lazypc.input.keyboard.core.KeyId
import com.example.lazypc.webrtc.WebRTCClient


class KeyboardEmitter(

    private val webrtc: WebRTCClient

) {


    companion object {

        private const val TAG =
            "KEYBOARD"


        private const val PACKET_TEXT =
            0x50


        private const val PACKET_KEY =
            0x51


        private const val PACKET_SHORTCUT =
            0x52


        private const val PACKET_LANG_SET =
            0x53


        const val LANG_EN =
            0


        const val LANG_RU =
            1
    }


    // ================================================================
    // EMIT ACTION
    // ================================================================


    fun emit(
        action: KeyAction
    ) {


        Log.d(
            TAG,
            "ACTION -> $action"
        )


        when (action) {


            // ========================================================
            // TEXT
            // ========================================================


            is KeyAction.Text -> {

                sendText(
                    action.value
                )
            }


            // ========================================================
            // KEY
            // ========================================================


            is KeyAction.Key -> {

                sendKey(
                    action.keyId
                )
            }


            // ========================================================
            // SHORTCUT
            // ========================================================


            is KeyAction.Shortcut -> {

                sendShortcut(
                    action
                )
            }


            // ========================================================
            // PRINTABLE
            // ========================================================


            is KeyAction.Printable -> {


                Log.e(

                    TAG,

                    "Printable reached emitter: ${action.keyId}"
                )
            }
        }
    }


    // ================================================================
    // TEXT
    // ================================================================


    fun sendText(
        text: String
    ) {


        if (text.isEmpty()) {

            return
        }


        val utf8 =

            text.toByteArray(
                Charsets.UTF_8
            )


        val packet =

            ByteArray(
                1 + utf8.size
            )


        packet[0] =

            PACKET_TEXT.toByte()


        utf8.copyInto(

            destination = packet,

            destinationOffset = 1
        )


        Log.d(

            TAG,

            "TX TEXT -> $text"
        )


        send(
            packet
        )
    }


    // ================================================================
    // KEY
    // ================================================================


    fun sendKey(
        keyId: KeyId
    ) {


        val packet =

            byteArrayOf(

                PACKET_KEY.toByte(),

                keyId.ordinal.toByte()
            )


        Log.d(

            TAG,

            "TX KEY -> $keyId"
        )


        send(
            packet
        )
    }


    // ================================================================
    // SHORTCUT
    // ================================================================


    fun sendShortcut(
        action: KeyAction.Shortcut
    ) {


        val packet =

            byteArrayOf(

                PACKET_SHORTCUT.toByte(),

                action.modifier.ordinal.toByte(),

                action.key.ordinal.toByte()
            )


        Log.d(

            TAG,

            "TX SHORTCUT -> "
                    + "${action.modifier} "
                    + "+ ${action.key}"
        )


        send(
            packet
        )
    }


    // ================================================================
    // LANGUAGE
    // ================================================================


    fun sendLanguage(
        language: Int
    ) {


        if (
            language != LANG_EN
            &&
            language != LANG_RU
        ) {


            Log.e(

                TAG,

                "Invalid language: $language"
            )


            return
        }


        val packet =

            byteArrayOf(

                PACKET_LANG_SET.toByte(),

                language.toByte()
            )


        Log.d(

            TAG,

            "TX LANGUAGE -> $language"
        )


        send(
            packet
        )
    }


    // ================================================================
    // SEND
    // ================================================================


    private fun send(
        packet: ByteArray
    ) {


        val success =

            webrtc.sendBinary(
                packet
            )


        if (!success) {


            Log.w(

                TAG,

                "DataChannel packet was not sent"
            )
        }
    }
}