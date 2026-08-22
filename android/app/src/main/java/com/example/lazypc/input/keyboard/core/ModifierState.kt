package com.example.lazypc.input.keyboard.core

class ModifierState {
    private val active = mutableSetOf<Modifier>()

    fun isActive(modifier: Modifier): Boolean =
        modifier in active

    fun toggle(modifier: Modifier) {
        if (!active.add(modifier)) {
            active.remove(modifier)
        }
    }

    fun clear() {
        active.clear()
    }

    fun snapshot(): Set<Modifier> =
        active.toSet()
}