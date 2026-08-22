package com.example.lazypc.input.keyboard.core

import android.os.SystemClock
import android.util.Log
import com.example.lazypc.input.keyboard.mapping.Language
import com.example.lazypc.input.keyboard.mapping.LanguageEN
import com.example.lazypc.input.keyboard.mapping.LanguageRU
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow


class KeyboardEngine(
    private val resolver: com.example.lazypc.input.keyboard.core.ActionResolver,
    language: com.example.lazypc.input.keyboard.mapping.Language
) {

    companion object {

        private const val TAG = "KB_DEBUG"

        private const val DOUBLE_TAP_TIMEOUT = 300L
    }


    // ================================================================
    // LAYER
    // ================================================================

    private val _currentLayer =
        MutableStateFlow(com.example.lazypc.input.keyboard.core.KeyboardLayer.TEXT)

    val currentLayer: StateFlow<com.example.lazypc.input.keyboard.core.KeyboardLayer> =
        _currentLayer.asStateFlow()


    // ================================================================
    // LANGUAGE
    // ================================================================

    private val _currentLanguage =
        MutableStateFlow(language)

    val currentLanguage: StateFlow<com.example.lazypc.input.keyboard.mapping.Language> =
        _currentLanguage.asStateFlow()


    // ================================================================
    // SHIFT
    // ================================================================

    private val _shiftEnabled =
        MutableStateFlow(false)

    val shiftEnabled: StateFlow<Boolean> =
        _shiftEnabled.asStateFlow()


    // ================================================================
    // CAPS LOCK
    // ================================================================

    private val _capsLockEnabled =
        MutableStateFlow(false)

    val capsLockEnabled: StateFlow<Boolean> =
        _capsLockEnabled.asStateFlow()


    private var lastShiftTapTime = 0L


    // ================================================================
    // SET LAYER
    // ================================================================

    fun setLayer(
        layer: com.example.lazypc.input.keyboard.core.KeyboardLayer
    ) {

        Log.d(
            TAG,
            "SET LAYER -> $layer"
        )

        _currentLayer.value = layer
    }


    // ================================================================
    // SWITCH LANGUAGE
    // ================================================================

    fun switchLanguage() {

        val newLanguage =

            when (_currentLanguage.value) {

                is com.example.lazypc.input.keyboard.mapping.LanguageEN ->
                    com.example.lazypc.input.keyboard.mapping.LanguageRU()

                is com.example.lazypc.input.keyboard.mapping.LanguageRU ->
                    com.example.lazypc.input.keyboard.mapping.LanguageEN()

                else ->
                    com.example.lazypc.input.keyboard.mapping.LanguageEN()
            }


        _currentLanguage.value =
            newLanguage


        Log.d(
            TAG,
            "LANGUAGE -> ${languageName()}"
        )
    }


    // ================================================================
    // LANGUAGE NAME
    // ================================================================

    fun languageName(): String {

        return when (_currentLanguage.value) {

            is com.example.lazypc.input.keyboard.mapping.LanguageEN ->
                "EN"

            is com.example.lazypc.input.keyboard.mapping.LanguageRU ->
                "RU"

            else ->
                "EN"
        }
    }


    // ================================================================
    // HANDLE KEY
    // ================================================================

    fun handleKey(
        keyId: com.example.lazypc.input.keyboard.core.KeyId
    ): com.example.lazypc.input.keyboard.core.KeyAction? {


        Log.d(
            TAG,
            "ENGINE: $keyId layer=${_currentLayer.value}"
        )


        when (keyId) {


            // ========================================================
            // TEXT LAYER
            // ========================================================

           com.example.lazypc.input.keyboard.core.KeyId.SWITCH_TEXT -> {

                setLayer(
                    com.example.lazypc.input.keyboard.core.KeyboardLayer.TEXT
                )

                return null
            }


            // ========================================================
            // SYMBOL LAYER
            // ========================================================

          com.example.lazypc.input.keyboard.core.KeyId.SWITCH_CODE -> {

                setLayer(
                    com.example.lazypc.input.keyboard.core.KeyboardLayer.CODE
                )

                return null
            }


            // ========================================================
            // SYSTEM / DEV LAYER
            // ========================================================

            com.example.lazypc.input.keyboard.core.KeyId.SWITCH_SYS -> {

                setLayer(
                    com.example.lazypc.input.keyboard.core.KeyboardLayer.SYS
                )

                return null
            }


            // ========================================================
            // SHIFT
            // ========================================================

           com.example.lazypc.input.keyboard.core.KeyId.SHIFT -> {


                val now =
                    SystemClock.elapsedRealtime()


                val isDoubleTap =

                    now - lastShiftTapTime <
                            DOUBLE_TAP_TIMEOUT


                lastShiftTapTime =
                    now


                when {


                    // CAPS -> OFF

                    _capsLockEnabled.value -> {

                        _capsLockEnabled.value =
                            false


                        Log.d(
                            TAG,
                            "CAPS OFF"
                        )
                    }


                    // DOUBLE TAP -> CAPS

                    isDoubleTap -> {

                        _capsLockEnabled.value =
                            true


                        _shiftEnabled.value =
                            false


                        Log.d(
                            TAG,
                            "CAPS LOCK ON"
                        )
                    }


                    // SINGLE TAP -> SHIFT

                    else -> {

                        _shiftEnabled.value =
                            !_shiftEnabled.value


                        Log.d(
                            TAG,
                            "SHIFT: ${_shiftEnabled.value}"
                        )
                    }
                }


                return null
            }


            else -> Unit
        }


        // ============================================================
        // RESOLVE ACTION
        // ============================================================

        val action =

            resolver.resolve(

                _currentLayer.value,

                keyId

            ) ?: return null


        // ============================================================
        // PRINTABLE
        // ============================================================

        return when (action) {


            is KeyAction.Printable -> {


                val text =

                    _currentLanguage.value.map(

                        keyId,

                        _shiftEnabled.value ||
                                _capsLockEnabled.value

                    ) ?: return null


                Log.d(
                    TAG,
                    "MAP -> $text"
                )


                // Обычный SHIFT сбрасываем после символа.
                // CAPS остаётся включённым.

                if (
                    _shiftEnabled.value &&
                    !_capsLockEnabled.value
                ) {

                    _shiftEnabled.value =
                        false


                    Log.d(
                        TAG,
                        "SHIFT RESET"
                    )
                }


                KeyAction.Text(
                    text
                )
            }


            else ->
                action
        }
    }
}