package com.example.lazypc.keyboard.mapping

import com.example.lazypc.keyboard.core.KeyId

interface Language {
    fun map(keyId: KeyId, shift: Boolean): String?
}