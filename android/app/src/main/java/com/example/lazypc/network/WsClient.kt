package com.example.lazypc.network

import android.util.Log
import okhttp3.*
import okio.ByteString
import org.json.JSONObject

class WsClient(
    private val url: String
) {

    private val client = OkHttpClient()
    private var socket: WebSocket? = null

    private var onText: ((String) -> Unit)? = null

    fun setOnTextMessage(callback: (String) -> Unit) {
        onText = callback
    }

    fun connect() {
        if (socket != null) return

        val request = Request.Builder()
            .url(url)
            .build()

        socket = client.newWebSocket(request, listener)
    }

    fun sendText(text: String) {
        Log.d("WS", "📤 TEXT: $text")
        socket?.send(text)
    }

    fun sendBinary(data: ByteArray) {
        socket?.send(ByteString.of(*data))
    }

    fun sendAnswer(sdp: String) {
        val json = JSONObject()
        json.put("type", "answer")
        json.put("sdp", sdp)

        sendText(json.toString())
    }
    fun sendOffer(sdp: String) {

        val json = JSONObject()

        json.put("type", "offer")
        json.put("sdp", sdp)

        sendText(json.toString())
    }

    fun sendCandidate(

        candidate: String,

        sdpMid: String?,

        sdpMLineIndex: Int

    ) {

        val json = JSONObject()

        json.put("type", "candidate")
        json.put("candidate", candidate)
        json.put("sdpMid", sdpMid)
        json.put("sdpMLineIndex", sdpMLineIndex)

        sendText(json.toString())
    }

    fun sendJson(json: JSONObject) {

        sendText(json.toString())

    }
    private val listener = object : WebSocketListener() {

        override fun onOpen(ws: WebSocket, response: Response) {
            Log.d("WS", "🟢 CONNECTED")

            // 🔥 ВОТ ЭТО КРИТИЧНО (ЭТО И БЫЛ БАГ)
            ws.send("HELLO_CLIENT")
        }

        override fun onMessage(ws: WebSocket, text: String) {
            Log.d("WS", "📥 TEXT: $text")
            onText?.invoke(text)
        }

        override fun onMessage(ws: WebSocket, bytes: ByteString) {
            // можно использовать позже
        }

        override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
            Log.e("WS", "❌ ERROR", t)
        }
    }
}