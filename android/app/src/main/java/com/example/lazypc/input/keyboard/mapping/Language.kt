package com.example.lazypc.input.keyboard.mapping

import com.example.lazypc.input.keyboard.core.KeyId


interface Language {
    fun map(keyId: KeyId, shift: Boolean): String?
}