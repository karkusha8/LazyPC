package com.example.lazypc.security

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

data class TrustedPc(
    val pcCode: String,
    val name: String
)

class TrustedPcStore(context: Context) {
    private val prefs = context.getSharedPreferences("trusted_pcs", Context.MODE_PRIVATE)

    fun list(): List<TrustedPc> {
        val raw = prefs.getString("devices", null) ?: return emptyList()
        return try {
            val array = JSONArray(raw)
            buildList {
                for (i in 0 until array.length()) {
                    val item = array.optJSONObject(i) ?: continue
                    val code = item.optString("pc_code").filter { it.isDigit() }
                    if (code.length == 9) {
                        add(TrustedPc(code, item.optString("name").ifBlank { "Компьютер" }))
                    }
                }
            }
        } catch (_: Throwable) { emptyList() }
    }

    fun addOrUpdate(pcCode: String, name: String? = null) {
        val code = pcCode.filter { it.isDigit() }
        if (code.length != 9) return
        val items = list().toMutableList()
        val index = items.indexOfFirst { it.pcCode == code }
        if (index >= 0) {
            val old = items[index]
            items[index] = old.copy(name = name?.takeIf { it.isNotBlank() } ?: old.name)
        } else {
            items += TrustedPc(code, name?.takeIf { it.isNotBlank() } ?: "Компьютер ${items.size + 1}")
        }
        save(items)
    }

    fun remove(pcCode: String) {
        val code = pcCode.filter { it.isDigit() }
        save(list().filterNot { it.pcCode == code })
    }

    private fun save(items: List<TrustedPc>) {
        val array = JSONArray()
        items.forEach { pc ->
            array.put(JSONObject().apply {
                put("pc_code", pc.pcCode)
                put("name", pc.name)
            })
        }
        prefs.edit().putString("devices", array.toString()).apply()
    }
}
