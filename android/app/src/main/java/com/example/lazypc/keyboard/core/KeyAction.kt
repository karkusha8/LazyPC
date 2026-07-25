package com.example.lazypc.keyboard.core

sealed class KeyAction {

    // 🔤 печатаемый ключ (через Language)
    data class Printable(val keyId: KeyId) : KeyAction()

    // 🔠 уже готовый текст (после mapping)
    data class Text(val value: String) : KeyAction()

    // ⌨️ системные кнопки
    data class Key(val keyId: KeyId) : KeyAction()

    // 🔗 комбинации (ctrl+c и т.д.)
    data class Shortcut(
        val modifier: KeyId,
        val key: KeyId
    ) : KeyAction()
}