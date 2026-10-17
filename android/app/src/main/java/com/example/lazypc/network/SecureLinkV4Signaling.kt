package com.example.lazypc.network

import android.util.Log
import com.example.lazypc.security.SecureLinkV4
import org.json.JSONObject

/** Small WebSocket adapter; it deliberately does not expose or send the QR PSK. */
class SecureLinkV4Signaling(private val ws: WsClient) {
    fun subscribe(room: ByteArray): Boolean =
        ws.sendJson(SecureLinkV4.subscribe(room))

    fun send(room: ByteArray, kind: String, payload: ByteArray): Boolean =
        ws.sendJson(SecureLinkV4.envelope(room, kind, payload))

    /** Feed only a parsed server message of type secure_link to this method. */
    fun parseIncoming(jsonText: String): SecureLinkV4.Envelope? = try {
        SecureLinkV4.parseEnvelope(JSONObject(jsonText))
    } catch (error: Exception) {
        Log.w("LazyPC-SecureLink", "Dropped malformed Secure Link envelope", error)
        null
    }
}
