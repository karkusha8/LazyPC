package com.example.lazypc.security

import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Android-side Secure Link v4 pairing protocol state machine over Rust/snow.
 * Signaling remains an untrusted byte relay; callers send/receive the returned
 * opaque payloads using pair1/pair2/pair3/pair4 plus the authenticated code_ok acknowledgement.
 */
class SecureLinkV4PairingHandshake(
    private val invitation: SecureLinkV4.Invitation,
    identity: SecureLinkNoiseKeyStore.StaticIdentity
) : AutoCloseable {
    enum class State { CREATED, WAIT_PAIR2, WAIT_PAIR4, PAIRED, REJECTED, FAILED, CLOSED }

    private val noise = SecureLinkNoiseSession.pairingInitiator(
        localPrivateKey = identity.privateKey,
        pcStaticPublicKey = invitation.pcStaticPublic,
        psk = invitation.psk
    )
    private val phoneStaticPublic = identity.publicKey.copyOf()
    private var currentState = State.CREATED
    private var transcriptHash: ByteArray? = null

    val state: State get() = currentState

    fun createPair1(): ByteArray {
        check(currentState == State.CREATED) { "pair1 already sent" }
        val message = noise.writeMessage(ByteArray(0))
        currentState = State.WAIT_PAIR2
        return message
    }

    /** Returns the six-digit code that must be displayed only on the phone. */
    fun receivePair2(message: ByteArray): String {
        check(currentState == State.WAIT_PAIR2) { "Unexpected pair2" }
        try {
            val plaintext = noise.readMessage(message)
            check(noise.isHandshakeFinished) { "Noise pairing handshake did not finish" }
            val reply = JSONObject(String(plaintext, StandardCharsets.UTF_8))
            require(reply.optInt("v", -1) == 4) { "Unsupported Secure Link pairing version" }
            val hash = noise.handshakeHash()
            require(hash.size == 32) { "Unexpected Noise handshake hash size" }
            transcriptHash = hash
            return SecureLinkV4.sasCode(hash)
        } catch (error: Exception) {
            currentState = State.FAILED
            noise.close()
            throw error
        }
    }

    /** Verify Windows' authenticated acknowledgement after the user entered the SAS. */
    fun verifyCodeAcceptedProof(proof: ByteArray): Boolean {
        val hash = transcriptHash ?: return false
        if (proof.size != 32) return false
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(invitation.psk, "HmacSHA256"))
        val expected = mac.doFinal(
            "LAZYPC/PAIR_CODE_ACCEPTED/v4".toByteArray(StandardCharsets.US_ASCII) + hash
        )
        return try { MessageDigest.isEqual(expected, proof) } finally { expected.fill(0) }
    }

    /** Exact transcript the StrongBox P-256 enrollment key must sign after biometric auth. */
    fun pairingTranscript(enrollmentKey: SecureLinkStrongBox.EnrollmentKey): ByteArray {
        check(currentState == State.WAIT_PAIR2) { "Pairing handshake is not awaiting registration" }
        val hash = transcriptHash ?: error("pair2 has not been processed")
        return SecureLinkV4.pairingTranscript(
            handshakeHash = hash,
            pcStaticPublic = invitation.pcStaticPublic,
            phoneStaticPublic = phoneStaticPublic,
            hardwarePublicDer = enrollmentKey.publicKeyDer,
            qrNonce = invitation.nonce
        )
    }

    /** Encrypts the StrongBox registration only after the caller completes biometric signing. */
    fun createPair3(
        enrollmentKey: SecureLinkStrongBox.EnrollmentKey,
        hardwareSignature: ByteArray,
        manufacturer: String,
        model: String,
        androidVersion: String
    ): ByteArray {
        check(currentState == State.WAIT_PAIR2) { "Unexpected pair3 creation" }
        require(hardwareSignature.isNotEmpty()) { "StrongBox signature is required" }
        val payload = JSONObject().apply {
            put("hw_public", Base64.encodeToString(enrollmentKey.publicKeyDer, Base64.NO_WRAP))
            put("hw_signature", Base64.encodeToString(hardwareSignature, Base64.NO_WRAP))
            put("attestation_chain", JSONArray().apply {
                enrollmentKey.attestationChainBase64.forEach { put(it) }
            })
            put("platform", "android")
            put("manufacturer", manufacturer.take(64))
            put("model", model.take(64))
            put("android_version", androidVersion.take(64))
        }.toString().toByteArray(StandardCharsets.UTF_8)
        return try {
            noise.writeMessage(payload).also { currentState = State.WAIT_PAIR4 }
        } catch (error: Exception) {
            currentState = State.FAILED
            noise.close()
            throw error
        }
    }

    fun receivePair4(message: ByteArray): Boolean {
        check(currentState == State.WAIT_PAIR4) { "Unexpected pair4" }
        return try {
            val plaintext = noise.readMessage(message)
            val reply = JSONObject(String(plaintext, StandardCharsets.UTF_8))
            when (reply.optString("status")) {
                "PAIRED" -> { currentState = State.PAIRED; true }
                "REJECTED" -> { currentState = State.REJECTED; false }
                else -> error("Unknown pair4 status")
            }
        } catch (error: Exception) {
            currentState = State.FAILED
            throw error
        } finally {
            noise.close()
        }
    }

    override fun close() {
        if (currentState != State.PAIRED && currentState != State.REJECTED) {
            currentState = State.CLOSED
        }
        noise.close()
        transcriptHash?.fill(0)
        transcriptHash = null
        phoneStaticPublic.fill(0)
    }
}
