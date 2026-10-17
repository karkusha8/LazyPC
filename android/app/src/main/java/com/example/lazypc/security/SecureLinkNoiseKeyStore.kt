package com.example.lazypc.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Persists the phone's X25519 Noise static key, encrypted at rest with a non-exportable
 * Android Keystore AES-GCM key. This is separate from the per-pairing StrongBox P-256
 * attestation/signing key in SecureLinkStrongBox.
 */
class SecureLinkNoiseKeyStore(context: Context) {
    data class StaticIdentity(val privateKey: ByteArray, val publicKey: ByteArray)

    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("secure_link_v4_noise", Context.MODE_PRIVATE)
    private val lock = Any()

    fun loadOrCreate(): StaticIdentity = synchronized(lock) {
        val stored = prefs.getString(KEY_MATERIAL, null)
        if (stored != null) {
            val packed = decrypt(Base64.decode(stored, Base64.NO_WRAP))
            require(packed.size == 64) { "Stored Secure Link Noise key has an invalid length" }
            return@synchronized StaticIdentity(
                privateKey = packed.copyOfRange(0, 32),
                publicKey = packed.copyOfRange(32, 64)
            ).also { packed.fill(0) }
        }

        val pair = SecureLinkNoiseSession.generateStaticKeyPair()
        val identity = StaticIdentity(pair.privateKey.copyOf(), pair.publicKey.copyOf())
        val packed = pair.privateKey + pair.publicKey
        try {
            val encrypted = encrypt(packed)
            val saved = prefs.edit()
                .putString(KEY_MATERIAL, Base64.encodeToString(encrypted, Base64.NO_WRAP))
                .commit()
            check(saved) { "Could not persist Secure Link Noise identity" }
        } finally {
            packed.fill(0)
            pair.privateKey.fill(0)
        }
        identity
    }

    /** Explicit local reset only; removing a Trusted PC must not call this. */
    fun deleteIdentity() = synchronized(lock) {
        prefs.edit().remove(KEY_MATERIAL).commit()
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        if (keyStore.containsAlias(WRAPPING_KEY_ALIAS)) keyStore.deleteEntry(WRAPPING_KEY_ALIAS)
    }

    private fun encrypt(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, wrappingKey())
        val ciphertext = cipher.doFinal(plain)
        return cipher.iv + ciphertext
    }

    private fun decrypt(blob: ByteArray): ByteArray {
        require(blob.size > GCM_IV_BYTES + GCM_TAG_BYTES) { "Stored Noise identity ciphertext is truncated" }
        val iv = blob.copyOfRange(0, GCM_IV_BYTES)
        val ciphertext = blob.copyOfRange(GCM_IV_BYTES, blob.size)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, wrappingKey(), GCMParameterSpec(GCM_TAG_BITS, iv))
        return cipher.doFinal(ciphertext)
    }

    private fun wrappingKey(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (keyStore.getKey(WRAPPING_KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(
                WRAPPING_KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setRandomizedEncryptionRequired(true)
                .build()
        )
        return generator.generateKey()
    }

    private companion object {
        const val KEY_MATERIAL = "noise_static_identity_v1"
        const val WRAPPING_KEY_ALIAS = "lazypc_secure_link_v4_noise_wrap"
        const val GCM_IV_BYTES = 12
        const val GCM_TAG_BYTES = 16
        const val GCM_TAG_BITS = 128
    }
}
