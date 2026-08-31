package com.example.lazypc.security.ordinary

import android.util.Base64
import android.util.Log
import com.example.lazypc.security.SecurityKeyStore
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.PublicKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import java.security.SecureRandom
import java.security.interfaces.ECPublicKey

/**
 * Android side of LazyPC Ordinary V2.
 *
 * This class owns only the authentication state. WebSocket transport remains
 * in WsClient. The 9-digit secret is supplied by the UI and is never put into
 * signaling.
 */
class OrdinaryAuthenticator(
    private val keyStore: SecurityKeyStore,
    private val send: (JSONObject) -> Boolean,
) {
    companion object {
        private const val TAG = "LazyPC-Ordinary"

        private const val VERSION = 2
        private const val IDENTITY_ALGORITHM = "ECDSA-P256"
        private const val KEY_EXCHANGE_ALGORITHM = "ECDH-P256"
        private const val KDF_ALGORITHM = "HKDF-SHA256"
        private const val CONFIRMATION_ALGORITHM = "HMAC-SHA256"

        private const val CLIENT_IDENTITY_DOMAIN =
            "LazyPC/OrdinaryV2/client-identity-proof"
        private const val CLIENT_PROOF_DOMAIN =
            "LazyPC/OrdinaryV2/client-proof"
        private const val SERVER_IDENTITY_DOMAIN =
            "LazyPC/OrdinaryV2/server-identity-proof"
        private const val SECRET_KEY_DOMAIN =
            "LazyPC/OrdinaryV2/secret-key"
        private const val SECRET_PROOF_DOMAIN =
            "LazyPC/OrdinaryV2/secret-proof"

        private const val CONFIRMATION_CLIENT_DOMAIN =
            "LazyPC/OrdinaryV2/key-confirmation/client"
        private const val CONFIRMATION_SERVER_DOMAIN =
            "LazyPC/OrdinaryV2/key-confirmation/server"

        private const val AES_GCM_NONCE_SIZE = 12
        private const val AES_GCM_TAG_BITS = 128
        private const val SESSION_KEY_SIZE = 32
    }

    private val secureRandom = SecureRandom()

    private var challenge: JSONObject? = null

    private var sessionId: String? = null
    private var pcId: String? = null
    private var nonceB64: String? = null
    private var windowsIdentityPublic: String? = null
    private var windowsEphemeralPublic: ByteArray? = null

    private var androidEphemeral: KeyPair? = null
    private var transcriptHash: ByteArray? = null
    private var confirmationKey: ByteArray? = null

    fun hasPendingChallenge(): Boolean = challenge != null
    fun isAuthenticated(): Boolean = sessionId != null && confirmationKey != null

    fun acceptChallenge(json: JSONObject): Boolean {
        return try {
            require(json.optString("type") == "ordinary_auth_challenge")
            require(json.optInt("version", -1) == VERSION)
            require(json.optString("pc_identity_public").isNotBlank())
            require(json.optString("pc_ephemeral_public").isNotBlank())
            require(json.optString("session_id").isNotBlank())
            require(json.optString("pc_id").isNotBlank())
            require(json.optString("nonce").isNotBlank())

            val algorithms = json.optJSONObject("algorithms")
            require(algorithms != null)
            require(algorithms.optString("identity") == IDENTITY_ALGORITHM)
            require(algorithms.optString("key_exchange") == KEY_EXCHANGE_ALGORITHM)
            require(algorithms.optString("kdf") == KDF_ALGORITHM)
            require(algorithms.optString("confirmation") == CONFIRMATION_ALGORITHM)

            // Do not accept another challenge over an active authentication.
            if (sessionId != null || confirmationKey != null) {
                clear()
            }

            challenge = JSONObject(json.toString())
            true
        } catch (t: Throwable) {
            Log.e(TAG, "Invalid Ordinary V2 challenge", t)
            clear()
            false
        }
    }

    /**
     * Called by the UI after the user enters the 9-digit code shown on Windows.
     */
    fun submitSecret(secret: String): Boolean {
        val pending = challenge ?: return false

        if (secret.length != 9 || !secret.all { it in '0'..'9' }) {
            Log.e(TAG, "Ordinary secret must contain exactly 9 digits")
            return false
        }

        return try {
            buildClientResponse(pending, secret)
        } catch (t: Throwable) {
            Log.e(TAG, "Ordinary client response failed", t)
            clear()
            false
        }
    }

    private fun buildClientResponse(json: JSONObject, secret: String): Boolean {
        keyStore.ensureKeys()

        val sid = json.getString("session_id")
        val pc = json.getString("pc_id")
        val nonce = json.getString("nonce")
        val winIdentity = json.getString("pc_identity_public")
        val winEphemeralB64 = json.getString("pc_ephemeral_public")

        val winEphemeralDer = decodeBase64(winEphemeralB64)
        val winEphemeralKey = loadP256PublicKey(winEphemeralDer)

        val ephemeral = generateEphemeral()
        val androidIdentity = keyStore.identityPublicKeyBase64()
        val androidEphemeralB64 =
            Base64.encodeToString(ephemeral.public.encoded, Base64.NO_WRAP)

        val fields = listOf(
            "protocol_version" to OrdinaryTranscript.text("2"),
            "session_id" to OrdinaryTranscript.text(sid),
            "pc_id" to OrdinaryTranscript.text(pc),
            "windows_identity_public" to OrdinaryTranscript.text(winIdentity),
            "android_identity_public" to OrdinaryTranscript.text(androidIdentity),
            "windows_ephemeral_public" to winEphemeralDer,
            "android_ephemeral_public" to ephemeral.public.encoded,
            "nonce" to decodeBase64(nonce),
        )

        // Windows stores transcript values as bytes. In particular, the
        // ephemeral public keys and nonce are the decoded DER/raw bytes.
        val transcript = OrdinaryTranscript.build(fields)
        val th = MessageDigest.getInstance("SHA-256").digest(transcript)

        val sharedSecret = KeyAgreement.getInstance("ECDH").run {
            init(ephemeral.private)
            doPhase(winEphemeralKey, true)
            generateSecret()
        }

        val proofKey = deriveSecretProofKey(
            sharedSecret = sharedSecret,
            secret = secret,
            transcriptHash = th,
        )

        val identitySignature = keyStore.signIdentity(
            (
                    CLIENT_IDENTITY_DOMAIN.toByteArray(StandardCharsets.UTF_8) +
                            byteArrayOf('|'.code.toByte()) +
                            th
                    )
        )

        val secretProof = createSecretProof(
            proofKey = proofKey,
            transcriptHash = th,
        )

        val plaintext = JSONObject().apply {
            put("identity_signature", identitySignature)
            put("secret_proof", secretProof)
        }.toString().toByteArray(StandardCharsets.UTF_8)

        val aad =
            CLIENT_PROOF_DOMAIN.toByteArray(StandardCharsets.UTF_8) +
                    byteArrayOf('|'.code.toByte()) +
                    th

        val encryptedProof = encryptAesGcm(
            key = proofKey,
            plaintext = plaintext,
            aad = aad,
        )

        sessionId = sid
        pcId = pc
        nonceB64 = nonce
        windowsIdentityPublic = winIdentity
        windowsEphemeralPublic = winEphemeralDer
        androidEphemeral = ephemeral
        transcriptHash = th

        challenge = null

        return send(JSONObject().apply {
            put("type", "ordinary_auth_response")
            put("version", VERSION)
            put("session_id", sid)
            put("pc_id", pc)
            put("android_identity_public", androidIdentity)
            put("android_ephemeral_public", androidEphemeralB64)
            put(
                "encrypted_proof",
                Base64.encodeToString(encryptedProof, Base64.NO_WRAP),
            )
        })
    }

    /**
     * Verify Windows identity proof and derive session/confirmation keys.
     */
    fun handleServerProof(json: JSONObject): Boolean {
        return try {
            require(json.optString("type") == "ordinary_auth_server_proof")
            require(json.optInt("version", -1) == VERSION)
            require(json.optString("session_id") == sessionId)

            val pc = requireNotNull(pcId)
            require(json.optString("pc_id") == pc)

            val expectedWindowsIdentity = requireNotNull(windowsIdentityPublic)
            val receivedWindowsIdentity =
                json.optString("pc_identity_public")
            require(receivedWindowsIdentity == expectedWindowsIdentity)

            val signatureB64 = json.optString("pc_identity_signature")
            require(signatureB64.isNotBlank())

            val th = requireNotNull(transcriptHash)

            val payload =
                SERVER_IDENTITY_DOMAIN.toByteArray(StandardCharsets.UTF_8) +
                        byteArrayOf('|'.code.toByte()) +
                        th

            val publicKey = loadP256PublicKey(decodeBase64(receivedWindowsIdentity))
            val signature = decodeBase64(signatureB64)

            val verifier = Signature.getInstance("SHA256withECDSA")
            verifier.initVerify(publicKey)
            verifier.update(payload)
            require(verifier.verify(signature)) {
                "Windows identity proof is invalid."
            }

            val sharedSecret = deriveSharedSecret()
            confirmationKey = deriveKey(
                sharedSecret = sharedSecret,
                salt = th,
                info = (
                        "LazyPC/OrdinaryV2/key-confirmation|" +
                                requireNotNull(sessionId)
                        ).toByteArray(StandardCharsets.UTF_8),
            )

            true
        } catch (t: Throwable) {
            Log.e(TAG, "Ordinary server proof rejected", t)
            clear()
            false
        }
    }

    /**
     * Verify Windows -> Android confirmation and send Android -> Windows
     * confirmation.
     */
    fun handleServerKeyConfirmation(json: JSONObject): Boolean {
        return try {
            require(json.optString("type") == "ordinary_key_confirmation")
            require(json.optInt("version", -1) == VERSION)
            require(json.optString("direction") == "server")
            require(json.optString("session_id") == sessionId)

            val key = requireNotNull(confirmationKey)
            val th = requireNotNull(transcriptHash)
            val received = json.optString("confirmation")
            require(received.isNotBlank())

            val expected = hmac(
                key,
                CONFIRMATION_SERVER_DOMAIN.toByteArray(StandardCharsets.UTF_8) +
                        byteArrayOf('|'.code.toByte()) +
                        th,
            )

            require(
                MessageDigest.isEqual(
                    expected,
                    decodeBase64(received),
                )
            ) {
                "Windows key confirmation is invalid."
            }

            val clientConfirmation = hmac(
                key,
                CONFIRMATION_CLIENT_DOMAIN.toByteArray(StandardCharsets.UTF_8) +
                        byteArrayOf('|'.code.toByte()) +
                        th,
            )

            send(JSONObject().apply {
                put("type", "ordinary_key_confirmation")
                put("version", VERSION)
                put("direction", "client")
                put("session_id", requireNotNull(sessionId))
                put(
                    "confirmation",
                    Base64.encodeToString(
                        clientConfirmation,
                        Base64.NO_WRAP,
                    ),
                )
            })
        } catch (t: Throwable) {
            Log.e(TAG, "Ordinary key confirmation failed", t)
            clear()
            false
        }
    }

    fun handleComplete(json: JSONObject): Boolean {
        val ok = try {
            json.optString("type") == "ordinary_auth_complete" &&
                    json.optInt("version", -1) == VERSION &&
                    json.optString("session_id") == sessionId &&
                    json.optBoolean("authenticated", false)
        } catch (_: Throwable) {
            false
        }

        if (!ok) clear()
        return ok
    }

    fun clear() {
        challenge = null
        sessionId = null
        pcId = null
        nonceB64 = null
        windowsIdentityPublic = null
        windowsEphemeralPublic = null
        androidEphemeral = null
        transcriptHash = null
        confirmationKey = null
    }

    private fun generateEphemeral(): KeyPair =
        KeyPairGenerator.getInstance("EC").apply {
            initialize(ECGenParameterSpec("secp256r1"))
        }.generateKeyPair()

    private fun loadP256PublicKey(der: ByteArray): PublicKey {
        val key = KeyFactory.getInstance("EC")
            .generatePublic(X509EncodedKeySpec(der))

        require(
            (key as ECPublicKey)
                .params.curve.field.fieldSize == 256
        ) {
            "EC public key is not P-256."
        }

        return key
    }

    private fun deriveSharedSecret(): ByteArray {
        val pair = requireNotNull(androidEphemeral)
        val peer = loadP256PublicKey(
            requireNotNull(windowsEphemeralPublic)
        )

        return KeyAgreement.getInstance("ECDH").run {
            init(pair.private)
            doPhase(peer, true)
            generateSecret()
        }
    }

    private fun deriveSecretProofKey(
        sharedSecret: ByteArray,
        secret: String,
        transcriptHash: ByteArray,
    ): ByteArray {
        val secretMaterial =
            SECRET_KEY_DOMAIN.toByteArray(StandardCharsets.UTF_8) +
                    byteArrayOf('|'.code.toByte()) +
                    secret.toByteArray(StandardCharsets.US_ASCII)

        val secretHash =
            MessageDigest.getInstance("SHA-256").digest(secretMaterial)

        return MessageDigest.getInstance("SHA-256").digest(
            sharedSecret + secretHash + transcriptHash
        )
    }

    private fun createSecretProof(
        proofKey: ByteArray,
        transcriptHash: ByteArray,
    ): String {
        val message =
            SECRET_PROOF_DOMAIN.toByteArray(StandardCharsets.UTF_8) +
                    byteArrayOf('|'.code.toByte()) +
                    transcriptHash

        return Base64.encodeToString(
            hmac(proofKey, message),
            Base64.NO_WRAP,
        )
    }

    private fun encryptAesGcm(
        key: ByteArray,
        plaintext: ByteArray,
        aad: ByteArray,
    ): ByteArray {
        val nonce = ByteArray(AES_GCM_NONCE_SIZE)
        secureRandom.nextBytes(nonce)

        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(
            Cipher.ENCRYPT_MODE,
            SecretKeySpec(key.copyOf(32), "AES"),
            GCMParameterSpec(AES_GCM_TAG_BITS, nonce),
        )
        cipher.updateAAD(aad)

        return nonce + cipher.doFinal(plaintext)
    }

    private fun deriveKey(
        sharedSecret: ByteArray,
        salt: ByteArray,
        info: ByteArray,
    ): ByteArray {
        // RFC 5869 HKDF-SHA256.
        val extractMac = Mac.getInstance("HmacSHA256")
        extractMac.init(SecretKeySpec(salt, "HmacSHA256"))
        val prk = extractMac.doFinal(sharedSecret)

        val expandMac = Mac.getInstance("HmacSHA256")
        expandMac.init(SecretKeySpec(prk, "HmacSHA256"))

        val t1 = expandMac.doFinal(info + byteArrayOf(1))
        return t1.copyOf(SESSION_KEY_SIZE)
    }

    private fun hmac(key: ByteArray, data: ByteArray): ByteArray =
        Mac.getInstance("HmacSHA256").run {
            init(SecretKeySpec(key, "HmacSHA256"))
            doFinal(data)
        }

    private fun decodeBase64(value: String): ByteArray =
        Base64.decode(value, Base64.DEFAULT)
}
