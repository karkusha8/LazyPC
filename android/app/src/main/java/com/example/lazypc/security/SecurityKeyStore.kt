package com.example.lazypc.security

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import android.util.Base64
import java.nio.charset.StandardCharsets
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

class SecurityKeyStore {
    companion object {
        private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
        private const val IDENTITY_ALIAS = "lazypc_identity_ec"
        private const val WEBRTC_HW_ALIAS = "lazypc_webrtc_hw_ec_v1"

        private const val PREFS = "lazypc_security"
        private const val PREF_ATTESTATION_CHALLENGE = "webrtc_attestation_challenge"
        private const val PREF_IDENTITY_BINDING_PREFIX = "identity_device_binding_"

        private const val DEVICE_ALIAS_PREFIX = "lazypc_device_"
        private const val CURVE = "secp256r1"
        private const val SIGNATURE_ALGORITHM = "SHA256withECDSA"
    }

    private val keyStore: KeyStore =
        KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }

    fun ensureKeys() {
        ensureKey(IDENTITY_ALIAS)
    }

    private fun pcKeyId(pcIdentityPublic: String): String {
        require(pcIdentityPublic.isNotBlank()) { "PC identity is empty" }
        val digest = MessageDigest.getInstance("SHA-256")
            .digest(pcIdentityPublic.toByteArray(StandardCharsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }.take(32)
    }

    private fun deviceAlias(pcIdentityPublic: String): String =
        DEVICE_ALIAS_PREFIX + pcKeyId(pcIdentityPublic)

    fun ensureDeviceKeyForPc(pcIdentityPublic: String) {
        ensureKeys()
        ensureKey(deviceAlias(pcIdentityPublic))
    }

    /**
     * Creates a fresh Device Key for a new Trusted Device pairing.
     *
     * Identity and StrongBox credentials are intentionally untouched.
     * The Device Key is the per-PC/per-pairing credential and is rotated
     * whenever a new QR pairing is successfully initiated.
     */
    fun rotateDeviceKeyForPc(pcIdentityPublic: String) {
        ensureKeys()
        val alias = deviceAlias(pcIdentityPublic)

        if (keyStore.containsAlias(alias)) {
            keyStore.deleteEntry(alias)
        }

        ensureKey(alias)

        // A rotated Device Key invalidates the previous binding signature.
        // The new pairing will save a fresh binding after enrollment.
        // No Identity or StrongBox key is touched here.
    }

    fun devicePublicKeyBase64(pcIdentityPublic: String): String =
        Base64.encodeToString(
            publicKey(deviceAlias(pcIdentityPublic)).encoded,
            Base64.NO_WRAP
        )

    fun signAuthDevice(
        pcIdentityPublic: String,
        challenge: String
    ): String =
        signDeviceText(
            pcIdentityPublic,
            "LAZYPC_AUTH_V2|DEVICE|$pcIdentityPublic|$challenge"
        )

    fun signDeviceEnrollmentProof(
        pairingId: String,
        nonceB64: String,
        pcIdentityPublic: String,
        identityPublic: String,
        devicePublic: String
    ): String =
        signDeviceText(
            pcIdentityPublic,
            "LAZYPC_DEVICE_ENROLL_V2|$pairingId|$nonceB64|$pcIdentityPublic|$identityPublic|$devicePublic"
        )

    fun signIdentityDeviceBinding(
        pairingId: String,
        nonceB64: String,
        pcIdentityPublic: String,
        identityPublic: String,
        devicePublic: String
    ): String {
        val transcript =
            "LAZYPC_IDENTITY_BIND_V2|$pairingId|$nonceB64|$pcIdentityPublic|$identityPublic|$devicePublic"
                .toByteArray(StandardCharsets.UTF_8)
        return signIdentity(transcript)
    }

    fun saveIdentityBindingSignature(
        context: Context,
        pcIdentityPublic: String,
        signature: String
    ) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(
                PREF_IDENTITY_BINDING_PREFIX + pcKeyId(pcIdentityPublic),
                signature
            )
            .apply()
    }

    fun identityBindingSignature(
        context: Context,
        pcIdentityPublic: String
    ): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(
                PREF_IDENTITY_BINDING_PREFIX + pcKeyId(pcIdentityPublic),
                null
            )

    fun identityPublicKeyBase64(): String =
        Base64.encodeToString(
            publicKey(IDENTITY_ALIAS).encoded,
            Base64.NO_WRAP
        )

    fun signIdentity(data: ByteArray): String =
        sign(privateKey(IDENTITY_ALIAS), data)

    private fun signDeviceText(
        pcIdentityPublic: String,
        text: String
    ): String =
        sign(
            privateKey(deviceAlias(pcIdentityPublic)),
            text.toByteArray(StandardCharsets.UTF_8)
        )

    private fun ensureKey(alias: String) {
        if (keyStore.containsAlias(alias)) return

        val generator = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_EC,
            KEYSTORE_PROVIDER
        )

        val spec = KeyGenParameterSpec.Builder(
            alias,
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
        )
            .setAlgorithmParameterSpec(ECGenParameterSpec(CURVE))
            .setDigests(
                KeyProperties.DIGEST_SHA256,
                KeyProperties.DIGEST_SHA384,
                KeyProperties.DIGEST_SHA512
            )
            .build()

        generator.initialize(spec)
        generator.generateKeyPair()
    }

    private fun privateKey(alias: String): PrivateKey =
        keyStore.getKey(alias, null) as PrivateKey

    private fun publicKey(alias: String) =
        keyStore.getCertificate(alias)?.publicKey
            ?: error("Android Keystore certificate missing for alias: $alias")

    private fun sign(
        privateKey: PrivateKey,
        data: ByteArray
    ): String {
        val signature = Signature.getInstance(SIGNATURE_ALGORITHM)
        signature.initSign(privateKey)
        signature.update(data)
        return Base64.encodeToString(signature.sign(), Base64.NO_WRAP)
    }

    /*
     * One StrongBox credential per Android installation.
     *
     * The attestation challenge is the challenge used when this hardware
     * credential was FIRST enrolled. It is intentionally not replaced on
     * every new PC pairing.
     */
    fun createTrustedHardwareKeyForPairing(
        attestationChallenge: ByteArray,
        context: Context
    ): HardwareKeyInfo {
        ensureKeys()
        require(attestationChallenge.size >= 16) {
            "Pairing attestation challenge is too short"
        }

        if (keyStore.containsAlias(WEBRTC_HW_ALIAS)) {
            return getExistingWebRtcHardwareKey(context)
        }

        val generator = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_EC,
            KEYSTORE_PROVIDER
        )

        val spec = KeyGenParameterSpec.Builder(
            WEBRTC_HW_ALIAS,
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
        )
            .setAlgorithmParameterSpec(ECGenParameterSpec(CURVE))
            .setDigests(
                KeyProperties.DIGEST_SHA256,
                KeyProperties.DIGEST_SHA384,
                KeyProperties.DIGEST_SHA512
            )
            .setAttestationChallenge(attestationChallenge)
            .setIsStrongBoxBacked(true)
            .build()

        try {
            generator.initialize(spec)
            generator.generateKeyPair()
        } catch (error: StrongBoxUnavailableException) {
            throw IllegalStateException(
                "StrongBox is required for LazyPC Trusted Device enrollment",
                error
            )
        }

        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(
                PREF_ATTESTATION_CHALLENGE,
                Base64.encodeToString(attestationChallenge, Base64.NO_WRAP)
            )
            .apply()

        return getExistingWebRtcHardwareKey(context)
    }

    fun getExistingWebRtcHardwareKey(context: Context): HardwareKeyInfo {
        require(keyStore.containsAlias(WEBRTC_HW_ALIAS)) {
            "Trusted hardware key is not enrolled on this device"
        }

        return HardwareKeyInfo(
            publicKeyBase64 = hardwarePublicKeyBase64(),
            attestationChallengeBase64 = attestationChallengeBase64(context),
            attestationChainBase64 = attestationChainBase64(),
            strongBoxRequested = Build.VERSION.SDK_INT >= 28
        )
    }

    fun hardwarePublicKeyBase64(): String =
        Base64.encodeToString(
            publicKey(WEBRTC_HW_ALIAS).encoded,
            Base64.NO_WRAP
        )

    fun attestationChallengeBase64(context: Context): String {
        val value = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(PREF_ATTESTATION_CHALLENGE, null)
            ?: error("Hardware key enrollment metadata missing")
        return value
    }

    fun attestationChainBase64(): List<String> =
        keyStore.getCertificateChain(WEBRTC_HW_ALIAS)
            ?.map { Base64.encodeToString(it.encoded, Base64.NO_WRAP) }
            ?: emptyList()

    fun signHardwareProof(data: ByteArray): String =
        sign(privateKey(WEBRTC_HW_ALIAS), data)

    data class HardwareKeyInfo(
        val publicKeyBase64: String,
        val attestationChallengeBase64: String,
        val attestationChainBase64: List<String>,
        val strongBoxRequested: Boolean
    )
}