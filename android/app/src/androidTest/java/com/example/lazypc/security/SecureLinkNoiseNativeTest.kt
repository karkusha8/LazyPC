package com.example.lazypc.security

import androidx.test.ext.junit.runners.AndroidJUnit4
import junit.framework.TestCase.assertEquals
import junit.framework.TestCase.assertFalse
import junit.framework.TestCase.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SecureLinkNoiseNativeTest {

    @Test
    fun nativeLibraryLoadsAndGeneratesX25519KeyPair() {
        val keys = SecureLinkNoiseSession.generateStaticKeyPair()

        try {
            assertEquals(32, keys.privateKey.size)
            assertEquals(32, keys.publicKey.size)
            assertFalse(keys.privateKey.all { it == 0.toByte() })
            assertFalse(keys.publicKey.all { it == 0.toByte() })
            assertTrue(keys.privateKey.indices.any {
                keys.privateKey[it] != keys.publicKey[it]
            })
        } finally {
            keys.privateKey.fill(0)
            keys.publicKey.fill(0)
        }
    }
}