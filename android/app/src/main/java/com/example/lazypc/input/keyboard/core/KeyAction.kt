package com.example.lazypc.input.keyboard.core

sealed class KeyAction {

    // 🔤 печатаемый ключ (через Language)
    data class Printable(val keyId: com.example.lazypc.input.keyboard.core.KeyId) : KeyAction()

    // 🔠 уже готовый текст (после mapping)
    data class Text(val value: String) : KeyAction()

    // ⌨️ системные кнопки
    data class Key(val keyId: com.example.lazypc.input.keyboard.core.KeyId) : KeyAction()

    // 🔗 комбинации (ctrl+c и т.д.)
    data class Shortcut(
        val modifier: com.example.lazypc.input.keyboard.core.KeyId,
        val key: com.example.lazypc.input.keyboard.core.KeyId
    ) : KeyAction()

    // ⌨️ удерживаемый модификатор
    data class Modifier(
        val keyId: com.example.lazypc.input.keyboard.core.KeyId,
        val pressed: Boolean
    ) : KeyAction()
}