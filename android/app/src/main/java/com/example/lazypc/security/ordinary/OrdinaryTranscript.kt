package com.example.lazypc.security.ordinary

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets
import java.security.MessageDigest

object OrdinaryTranscript {
    private val DOMAIN = "LAZYPC-ORDINARY-V2".toByteArray(StandardCharsets.US_ASCII)

    fun build(fields: List<Pair<String, ByteArray>>): ByteArray {
        require(fields.isNotEmpty()) { "Transcript must contain fields." }

        val out = ByteArrayOutputStream()
        out.write(DOMAIN)
        out.write(int32(fields.size))

        for ((name, value) in fields) {
            val nameBytes = name.toByteArray(StandardCharsets.US_ASCII)
            require(nameBytes.size <= 0xFFFF) { "Transcript field name is too long." }

            out.write(int16(nameBytes.size))
            out.write(nameBytes)

            require(value.size.toLong() <= 0xFFFFFFFFL) { "Transcript field value is too long." }
            out.write(int32(value.size))
            out.write(value)
        }

        return out.toByteArray()
    }

    fun digest(fields: List<Pair<String, ByteArray>>): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(build(fields))

    fun text(value: String): ByteArray =
        value.toByteArray(StandardCharsets.UTF_8)

    private fun int16(value: Int): ByteArray =
        ByteBuffer.allocate(2)
            .order(ByteOrder.BIG_ENDIAN)
            .putShort(value.toShort())
            .array()

    private fun int32(value: Int): ByteArray =
        ByteBuffer.allocate(4)
            .order(ByteOrder.BIG_ENDIAN)
            .putInt(value)
            .array()
}
