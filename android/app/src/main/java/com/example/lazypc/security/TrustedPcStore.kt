package com.example.lazypc.security

import android.content.Context
import android.util.Base64

/** A PC trusted through Secure Link v4. Identity is the pinned X25519 public key, not a numeric code. */
data class TrustedPc(
    val pcIdentityPublic: String,
    val hardwareAlias: String,
    val name: String
)

class TrustedPcStore(private val context: Context) {
    private val prefs = context.getSharedPreferences("secure_link_v4_trusted", Context.MODE_PRIVATE)

    fun list(): List<TrustedPc> {
        val all = prefs.all
        return all.keys
            .filter { it.startsWith(PC_STATIC_PREFIX) }
            .mapNotNull { staticEntry ->
                val identity = all[staticEntry] as? String ?: return@mapNotNull null
                if (identity.isBlank()) return@mapNotNull null
                val key = staticEntry.removePrefix(PC_STATIC_PREFIX)
                val alias = all[HW_ALIAS_PREFIX + key] as? String ?: return@mapNotNull null
                if (alias.isBlank()) return@mapNotNull null
                TrustedPc(
                    pcIdentityPublic = identity,
                    hardwareAlias = alias,
                    name = "Компьютер · ${identity.take(7)}"
                )
            }
            .sortedBy { it.name }
    }

    /** Called only after an authenticated Secure Link v4 pair4/PAIRED response. */
    fun addOrUpdate(pcIdentityPublic: String, hardwareAlias: String): Boolean {
        if (pcIdentityPublic.isBlank() || hardwareAlias.isBlank()) return false
        val key = pcIdentityPublic
        return prefs.edit()
            .putString(PC_STATIC_PREFIX + key, pcIdentityPublic)
            .putString(HW_ALIAS_PREFIX + key, hardwareAlias)
            .commit()
    }

    fun remove(pcIdentityPublic: String) {
        val key = pcIdentityPublic
        val alias = prefs.getString(HW_ALIAS_PREFIX + key, null)
        prefs.edit()
            .remove(PC_STATIC_PREFIX + key)
            .remove(HW_ALIAS_PREFIX + key)
            .commit()

        // Delete only this PC's session-authorization key; leave the phone's
        // persistent identity key and all other trusted PCs untouched.
        if (!alias.isNullOrBlank()) {
            try {
                SecureLinkStrongBox(context).deletePairingKey(alias)
            } catch (_: Throwable) {
                // Local trust removal should still work if the alias is already absent.
            }
        }
    }

    companion object {
        private const val PC_STATIC_PREFIX = "pc_static_"
        private const val HW_ALIAS_PREFIX = "hw_alias_"
    }
}
