package com.example.lazypc.security

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class TrustedPc(
    val pcCode: String,
    val name: String,
    val pcIdentityPublic: String? = null
)

class TrustedPcStore(private val context: Context) {

    private val prefs =
        context.getSharedPreferences(
            "trusted_pcs",
            Context.MODE_PRIVATE
        )

    fun list(): List<TrustedPc> {
        val raw =
            prefs.getString(
                "devices",
                null
            ) ?: return emptyList()

        return try {
            val array = JSONArray(raw)

            buildList {
                for (i in 0 until array.length()) {
                    val item =
                        array.optJSONObject(i)
                            ?: continue

                    val code =
                        item
                            .optString("pc_code")
                            .filter { it.isDigit() }

                    if (code.length == 9) {
                        add(
                            TrustedPc(
                                pcCode = code,
                                name = item
                                    .optString("name")
                                    .ifBlank {
                                        "Компьютер"
                                    },
                                pcIdentityPublic =
                                    item
                                        .optString(
                                            "pc_identity_public"
                                        )
                                        .takeIf {
                                            it.isNotBlank()
                                        }
                            )
                        )
                    }
                }
            }
        } catch (_: Throwable) {
            emptyList()
        }
    }

    fun addOrUpdate(
        pcCode: String,
        name: String? = null,
        pcIdentityPublic: String? = null
    ) {
        val code =
            pcCode
                .filter { it.isDigit() }

        if (code.length != 9) {
            return
        }

        val items =
            list().toMutableList()

        val index =
            items.indexOfFirst {
                it.pcCode == code
            }

        if (index >= 0) {
            val old = items[index]

            items[index] =
                old.copy(
                    name =
                        name?.takeIf {
                            it.isNotBlank()
                        } ?: old.name,

                    pcIdentityPublic =
                        pcIdentityPublic
                            ?.takeIf {
                                it.isNotBlank()
                            }
                            ?: old.pcIdentityPublic
                )
        } else {
            items +=
                TrustedPc(
                    pcCode = code,
                    name =
                        name?.takeIf {
                            it.isNotBlank()
                        }
                            ?: "Компьютер ${items.size + 1}",

                    pcIdentityPublic =
                        pcIdentityPublic
                            ?.takeIf {
                                it.isNotBlank()
                            }
                )
        }

        save(items)
    }

    fun remove(pcCode: String) {
        val code =
            pcCode
                .filter { it.isDigit() }

        val current = list()

        val pc =
            current.firstOrNull {
                it.pcCode == code
            }

        // Remove only the credentials belonging to this Trusted PC.
        // The global Android Identity Key and the global StrongBox key
        // remain untouched.
        pc?.pcIdentityPublic?.let { pcIdentityPublic ->
            try {
                SecurityKeyStore().deleteCredentialsForPc(
                    context = context,
                    pcIdentityPublic = pcIdentityPublic
                )
            } catch (_: Throwable) {
                // Keep local Trusted PC removal working even if the
                // keystore entry was already absent.
            }
        }

        save(
            current.filterNot {
                it.pcCode == code
            }
        )
    }

    private fun save(
        items: List<TrustedPc>
    ) {
        val array = JSONArray()

        items.forEach { pc ->
            array.put(
                JSONObject().apply {
                    put(
                        "pc_code",
                        pc.pcCode
                    )

                    put(
                        "name",
                        pc.name
                    )

                    pc.pcIdentityPublic
                        ?.takeIf {
                            it.isNotBlank()
                        }
                        ?.let {
                            put(
                                "pc_identity_public",
                                it
                            )
                        }
                }
            )
        }

        prefs
            .edit()
            .putString(
                "devices",
                array.toString()
            )
            .apply()
    }
}