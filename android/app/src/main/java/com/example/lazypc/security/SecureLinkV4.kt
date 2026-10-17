package com.example.lazypc.security

import android.util.Base64
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.URI
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest

/** Strict primitives for the Secure Link v4 wire format. No legacy QR formats accepted. */
object SecureLinkV4 {
    const val PROLOGUE = "lazypc/v4"
    const val NOISE_PAIRING = "Noise_IKpsk2_25519_ChaChaPoly_SHA256"
    const val NOISE_SESSION = "Noise_IK_25519_ChaChaPoly_SHA256"
    const val MAX_MESSAGE_BYTES = 64 * 1024

    private val allowedKinds = setOf("hello", "reply", "pair1", "pair2", "pair3", "pair4", "code_ok")

    data class Invitation(
        val pcStaticPublic: ByteArray,
        val psk: ByteArray,
        val nonce: ByteArray,
    ) {
        fun pairingRoom(): ByteArray = sha256("lazypc/room/pair/v4".toByteArray(Charsets.US_ASCII) + psk).copyOf(16)
        fun sessionRoom(): ByteArray = sha256("lazypc/room/session/v4".toByteArray(Charsets.US_ASCII) + pcStaticPublic).copyOf(16)
    }

    fun sessionRoom(pcStaticPublic: ByteArray): ByteArray {
        require(pcStaticPublic.size == 32) { "PC static public key must be 32 bytes" }
        return sha256("lazypc/room/session/v4".toByteArray(Charsets.US_ASCII) + pcStaticPublic).copyOf(16)
    }

    data class Envelope(val room: ByteArray, val kind: String, val data: ByteArray) {
        fun toJson(): JSONObject = JSONObject().apply {
            put("type", "secure_link")
            put("room", b64UrlEncode(room))
            put("kind", kind)
            put("data", Base64.encodeToString(data, Base64.NO_WRAP))
        }
    }

    fun parseQrPayload(payload: String): Invitation {
        require(payload.length <= 512) { "QR payload is too large" }
        val uri = try { URI(payload) } catch (e: Exception) {
            throw IllegalArgumentException("Invalid Secure Link QR", e)
        }
        require(uri.scheme == "lazypc" && uri.host == "pair" && uri.path == "/4") {
            "Unsupported pairing QR: expected lazypc://pair/4"
        }
        require(uri.userInfo == null && uri.port == -1 && uri.fragment == null) { "Invalid QR URL structure" }
        val query = parseQuery(uri.rawQuery ?: "")
        require(query.keys == setOf("pc", "psk", "n")) { "QR must contain only pc, psk and n" }
        val pc = b64UrlDecode(query.getValue("pc"))
        val psk = b64UrlDecode(query.getValue("psk"))
        val nonce = b64UrlDecode(query.getValue("n"))
        require(pc.size == 32) { "PC static public key must be 32 bytes" }
        require(psk.size == 32) { "Pairing PSK must be 32 bytes" }
        require(nonce.size == 32) { "QR nonce must be 32 bytes" }
        require(pc.any { it.toInt() != 0 }) { "Invalid all-zero PC public key" }
        return Invitation(pc, psk, nonce)
    }

    fun parseEnvelope(json: JSONObject): Envelope {
        require(json.optString("type") == "secure_link") { "Not a Secure Link envelope" }
        val room = b64UrlDecode(json.getString("room"))
        val kind = json.getString("kind")
        val data = try { Base64.decode(json.getString("data"), Base64.DEFAULT) } catch (e: Exception) {
            throw IllegalArgumentException("Invalid Secure Link payload encoding", e)
        }
        require(room.size == 16) { "Room must be 16 bytes" }
        require(kind in allowedKinds) { "Unsupported Secure Link message kind" }
        require(data.isNotEmpty() && data.size <= MAX_MESSAGE_BYTES) { "Invalid Secure Link payload size" }
        return Envelope(room, kind, data)
    }

    fun envelope(room: ByteArray, kind: String, data: ByteArray): JSONObject {
        require(room.size == 16) { "Room must be 16 bytes" }
        require(kind in allowedKinds) { "Unsupported Secure Link message kind" }
        require(data.isNotEmpty() && data.size <= MAX_MESSAGE_BYTES) { "Invalid Secure Link payload size" }
        return Envelope(room.copyOf(), kind, data.copyOf()).toJson()
    }

    fun subscribe(room: ByteArray): JSONObject {
        require(room.size == 16) { "Room must be 16 bytes" }
        return JSONObject().apply {
            put("type", "secure_link_subscribe")
            put("room", b64UrlEncode(room))
        }
    }

    fun enc(vararg parts: ByteArray): ByteArray {
        val output = ByteArrayOutputStream()
        parts.forEach { part ->
            require(part.size >= 0) { "Invalid transcript field" }
            output.write(ByteBuffer.allocate(4).order(ByteOrder.BIG_ENDIAN).putInt(part.size).array())
            output.write(part)
        }
        return output.toByteArray()
    }

    fun pairingTranscript(
        handshakeHash: ByteArray,
        pcStaticPublic: ByteArray,
        phoneStaticPublic: ByteArray,
        hardwarePublicDer: ByteArray,
        qrNonce: ByteArray,
    ): ByteArray = enc(
        "LAZYPC/PAIR/v4".toByteArray(Charsets.US_ASCII),
        handshakeHash,
        pcStaticPublic,
        phoneStaticPublic,
        hardwarePublicDer,
        qrNonce,
    )

    /** Canonical StrongBox authorization transcript; field order matches Windows secure_link.py. */
    fun sessionTranscript(
        scope: String,
        handshakeHash: ByteArray,
        pcStaticPublic: ByteArray,
        phoneStaticPublic: ByteArray,
        hardwarePublicDer: ByteArray,
        fpPc: ByteArray,
        fpPhone: ByteArray,
        nonce: ByteArray,
        sessionId: ByteArray,
    ): ByteArray = enc(
        "LAZYPC/AUTH/v4".toByteArray(Charsets.US_ASCII),
        scope.toByteArray(Charsets.UTF_8),
        handshakeHash,
        pcStaticPublic,
        phoneStaticPublic,
        hardwarePublicDer,
        fpPc,
        fpPhone,
        nonce,
        sessionId,
    )

    /** Extract the unique SHA-256 DTLS fingerprint, rejecting ambiguous SDP. */
    fun sdpFingerprint(sdp: String): ByteArray {
        val matches = Regex("(?im)^a=fingerprint:sha-256\\s+([0-9A-F]{2}(?::[0-9A-F]{2}){31})\\s*$")
            .findAll(sdp).map { it.groupValues[1].replace(":", "") }.toSet()
        require(matches.size == 1) { "SDP must contain exactly one SHA-256 DTLS fingerprint" }
        return matches.single().chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    }

    fun sasCode(handshakeHash: ByteArray): String {
        require(handshakeHash.size == 32) { "Noise handshake hash must be 32 bytes" }
        val digest = sha256("lazypc/sas".toByteArray(Charsets.US_ASCII) + handshakeHash)
        val unsigned = ByteBuffer.wrap(digest, 0, 4).order(ByteOrder.BIG_ENDIAN).int.toLong() and 0xffffffffL
        return (unsigned % 1_000_000L).toString().padStart(6, '0')
    }

    fun b64UrlEncode(bytes: ByteArray): String =
        Base64.encodeToString(bytes, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)

    fun b64UrlDecode(value: String): ByteArray {
        require(value.isNotEmpty() && value.length <= 128) { "Invalid base64url value" }
        require(value.matches(Regex("[A-Za-z0-9_-]+"))) { "Non-canonical base64url value" }
        val decoded = try { Base64.decode(value, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP) }
        catch (e: Exception) { throw IllegalArgumentException("Invalid base64url value", e) }
        require(b64UrlEncode(decoded) == value) { "Non-canonical base64url value" }
        return decoded
    }

    private fun parseQuery(raw: String): Map<String, String> {
        require(raw.isNotBlank()) { "Missing QR query" }
        val result = linkedMapOf<String, String>()
        raw.split('&').forEach { item ->
            val index = item.indexOf('=')
            require(index > 0 && index < item.lastIndex) { "Malformed QR query" }
            val key = item.substring(0, index)
            val value = item.substring(index + 1)
            require(key !in result) { "Duplicate QR field: $key" }
            result[key] = value
        }
        return result
    }

    private fun sha256(input: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(input)
}
