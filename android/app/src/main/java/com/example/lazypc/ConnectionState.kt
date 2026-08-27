package com.example.lazypc

sealed interface ConnectionState {
    data object Disconnected : ConnectionState
    data object Connecting : ConnectionState
    data object Connected : ConnectionState
    data object Disconnecting : ConnectionState
    data class Error(val message: String) : ConnectionState
}
