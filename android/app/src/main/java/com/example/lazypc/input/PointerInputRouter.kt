package com.example.lazypc.input

import android.view.MotionEvent
import com.example.lazypc.input.gesture.ClientGestureEngine
import kotlin.math.abs

class PointerInputRouter(
    private val gestureEngine: ClientGestureEngine
) {

    private var lastScrollY = 0f
    private var scrolling = false
    private var suppressNextUp = false


    fun onTouch(event: MotionEvent): Boolean {


        if (event.pointerCount == 2) {


            if (!scrolling) {

                scrolling = true
                suppressNextUp = true

                val y =
                    (event.getY(0) + event.getY(1)) / 2f

                lastScrollY = y

                gestureEngine.onScrollStart(
                    event.getX(0),
                    y
                )
            }


            handleScroll(event)

            return true
        }


        if (event.pointerCount == 1) {


            if (
                suppressNextUp &&
                event.actionMasked == MotionEvent.ACTION_UP
            ) {
                suppressNextUp = false
                return true
            }


            scrolling = false

            gestureEngine.handle(event)

            return true
        }


        return true
    }



    private fun handleScroll(
        event: MotionEvent
    ) {


        when(event.actionMasked){


            MotionEvent.ACTION_MOVE -> {


                val y =
                    (event.getY(0)+event.getY(1))/2f


                val dy =
                    lastScrollY - y


                /*
                 * Никаких шагов.
                 * Передаем реальное движение.
                 */

                if(abs(dy) > 0.5f){

                    gestureEngine.onScroll(dy)

                }


                lastScrollY = y
            }



            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_CANCEL -> {

                scrolling=false

            }

        }

    }
}