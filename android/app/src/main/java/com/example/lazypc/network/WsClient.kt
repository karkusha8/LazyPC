package com.example.lazypc.network

import okhttp3.*
import okio.ByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class WsClient(
    private val url: String
) {

    private val client = OkHttpClient.Builder()
        .pingInterval(15, TimeUnit.SECONDS)
        .build()

    private var socket: WebSocket? = null
    private var manuallyClosed = false

    private var onText: ((String) -> Unit)? = null
    private var onConnectionState: ((Boolean) -> Unit)? = null

    fun setOnTextMessage(callback: (String) -> Unit) {
        onText = callback
    }

    fun setOnConnectionState(callback: (Boolean) -> Unit) {
        onConnectionState = callback
    }

    @Synchronized
    fun connect() {
        if (socket != null) return

        manuallyClosed = false

        val request = Request.Builder()
            .url(url)
            .build()

        socket = client.newWebSocket(request, listener)
    }

    @Synchronized
    fun reconnectNow() {
        manuallyClosed = false

        val old = socket
        socket = null
        old?.close(1000, "Reconnect")

        connect()
    }

    @Synchronized
    fun isConnected(): Boolean = socket != null

    fun sendText(text: String): Boolean {
        return socket?.send(text) == true
    }

    fun sendBinary(data: ByteArray): Boolean {
        return socket?.send(ByteString.of(*data)) == true
    }

    fun sendAnswer(sdp: String) {
        val json = JSONObject().apply {
            put("type", "answer")
            put("sdp", sdp)
        }
        sendText(json.toString())
    }

    fun sendOffer(sdp: String) {
        val json = JSONObject().apply {
            put("type", "offer")
            put("sdp", sdp)
        }
        sendText(json.toString())
    }

    fun sendCandidate(
        candidate: String,
        sdpMid: String?,
        sdpMLineIndex: Int
    ) {
        val json = JSONObject().apply {
            put("type", "candidate")
            put("candidate", candidate)
            put("sdpMid", sdpMid)
            put("sdpMLineIndex", sdpMLineIndex)
        }
        sendText(json.toString())
    }

    fun sendJson(json: JSONObject) {
        sendText(json.toString())
    }

    @Synchronized
    private fun handleSocketEnded(
        endedSocket: WebSocket,
        reason: String
    ) {
        if (socket !== endedSocket) return

        socket = null
        onConnectionState?.invoke(false)
    }

    @Synchronized
    fun close() {
        manuallyClosed = true

        val current = socket
        socket = null

        current?.close(1000, "Client closed")
        onConnectionState?.invoke(false)
    }

    private val listener = object : WebSocketListener() {

        override fun onOpen(ws: WebSocket, response: Response) {
            synchronized(this@WsClient) {
                socket = ws
            }

            onConnectionState?.invoke(true)
            ws.send("HELLO_CLIENT")
        }

        override fun onMessage(ws: WebSocket, text: String) {
            onText?.invoke(text)
        }

        override fun onMessage(ws: WebSocket, bytes: ByteString) {
        }

        override fun onFailure(
            ws: WebSocket,
            t: Throwable,
            response: Response?
        ) {
            handleSocketEnded(ws, "failure")
        }

        override fun onClosed(
            ws: WebSocket,
            code: Int,
            reason: String
        ) {
            handleSocketEnded(ws, "closed")
        }
    }
}