package com.example.lazypc.security

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.security.MessageDigest

/** StrongBox enrollment-key primitives for Secure Link v4.
 * The caller must display a BiometricPrompt using prepareSignatureForBiometric(),
 * then call finishSignature() on the returned CryptoObject signature after success.
 */
class SecureLinkStrongBox(private val context: Context) {
    data class EnrollmentKey(
        val alias: String,
        val publicKeyDer: ByteArray,
        val publicKeyBase64: String,
        val attestationChainBase64: List<String>,
    )

    fun createFreshPairingKey(qrNonce: ByteArray): EnrollmentKey {
        require(qrNonce.size == 32) { "QR nonce must be 32 bytes" }
        val keyStore = androidKeyStore()
        val suffix = MessageDigest.getInstance("SHA-256").digest(qrNonce)
            .take(12).joinToString("") { "%02x".format(it) }
        val alias = "lazypc_secure_link_v4_$suffix"
        require(!keyStore.containsAlias(alias)) { "This QR nonce was already used on this device" }

        val builder = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setIsStrongBoxBacked(true)
            .setAttestationChallenge(qrNonce)
            .setUserAuthenticationRequired(true)
            .setInvalidatedByBiometricEnrollment(true)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            builder.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
        } else {
            @Suppress("DEPRECATION")
            builder.setUserAuthenticationValidityDurationSeconds(-1)
        }

        try {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
                .apply { initialize(builder.build()) }
                .generateKeyPair()
        } catch (e: Exception) {
            // Do not silently downgrade to TEE/software: StrongBox is a protocol requirement.
            throw IllegalStateException("StrongBox is required for Trusted Device pairing", e)
        }

        val publicDer = keyStore.getCertificate(alias).publicKey.encoded
        val chain = keyStore.getCertificateChain(alias)
            ?: throw IllegalStateException("StrongBox attestation chain is unavailable")
        return EnrollmentKey(
            alias = alias,
            publicKeyDer = publicDer,
            publicKeyBase64 = Base64.encodeToString(publicDer, Base64.NO_WRAP),
            attestationChainBase64 = chain.map { Base64.encodeToString(it.encoded, Base64.NO_WRAP) },
        )
    }

    /** Initialize this Signature before passing it to BiometricPrompt.CryptoObject. */
    fun prepareSignatureForBiometric(alias: String): Signature {
        val ks = androidKeyStore()
        require(ks.containsAlias(alias)) { "Enrollment key not found" }
        val privateKey = ks.getKey(alias, null) ?: throw IllegalStateException("Private key unavailable")
        return Signature.getInstance("SHA256withECDSA").apply { initSign(privateKey as java.security.PrivateKey) }
    }

    /** Call only with the Signature returned by a successful biometric CryptoObject. */
    fun finishSignature(signature: Signature, transcript: ByteArray): ByteArray {
        require(transcript.isNotEmpty()) { "Transcript must not be empty" }
        signature.update(transcript)
        return signature.sign()
    }

    fun deletePairingKey(alias: String) {
        androidKeyStore().deleteEntry(alias)
    }

    private fun androidKeyStore(): KeyStore =
        KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
}
