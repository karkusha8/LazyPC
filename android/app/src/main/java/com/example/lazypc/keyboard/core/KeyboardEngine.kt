package com.example.lazypc.keyboard.core

import android.os.SystemClock
import android.util.Log
import com.example.lazypc.keyboard.mapping.Language
import com.example.lazypc.keyboard.mapping.LanguageEN
import com.example.lazypc.keyboard.mapping.LanguageRU
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow


class KeyboardEngine(
    private val resolver: ActionResolver,
    language: Language
) {

    companion object {

        private const val TAG = "KB_DEBUG"

        private const val DOUBLE_TAP_TIMEOUT = 300L
    }


    // ================================================================
    // LAYER
    // ================================================================

    private val _currentLayer =
        MutableStateFlow(KeyboardLayer.TEXT)

    val currentLayer: StateFlow<KeyboardLayer> =
        _currentLayer.asStateFlow()


    // ================================================================
    // LANGUAGE
    // ================================================================

    private val _currentLanguage =
        MutableStateFlow(language)

    val currentLanguage: StateFlow<Language> =
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
        layer: KeyboardLayer
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

                is LanguageEN ->
                    LanguageRU()

                is LanguageRU ->
                    LanguageEN()

                else ->
                    LanguageEN()
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

            is LanguageEN ->
                "EN"

            is LanguageRU ->
                "RU"

            else ->
                "EN"
        }
    }


    // ================================================================
    // HANDLE KEY
    // ================================================================

    fun handleKey(
        keyId: KeyId
    ): KeyAction? {


        Log.d(
            TAG,
            "ENGINE: $keyId layer=${_currentLayer.value}"
        )


        when (keyId) {


            // ========================================================
            // TEXT LAYER
            // ========================================================

            KeyId.SWITCH_TEXT -> {

                setLayer(
                    KeyboardLayer.TEXT
                )

                return null
            }


            // ========================================================
            // SYMBOL LAYER
            // ========================================================

            KeyId.SWITCH_CODE -> {

                setLayer(
                    KeyboardLayer.CODE
                )

                return null
            }


            // ========================================================
            // SYSTEM / DEV LAYER
            // ========================================================

            KeyId.SWITCH_SYS -> {

                setLayer(
                    KeyboardLayer.SYS
                )

                return null
            }


            // ========================================================
            // SHIFT
            // ========================================================

            KeyId.SHIFT -> {


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