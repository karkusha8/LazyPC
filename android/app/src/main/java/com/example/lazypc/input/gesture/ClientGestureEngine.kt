package com.example.lazypc.input.gesture

import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import com.example.lazypc.input.events.GestureEvent
import kotlin.math.abs


class ClientGestureEngine(
    private val isDragModeEnabled: () -> Boolean,
    private val emit: (GestureEvent) -> Unit
) {


    companion object {

        // чувствительность скролла
        private const val SCROLL_SENSITIVITY = 1.0f

        // фильтр микродвижений пальца
        private const val SCROLL_DEAD_ZONE = 0.3f
    }


    private val state = GestureState()

    private val handler = Handler(Looper.getMainLooper())


    // накопление плавного scroll
    private var scrollAccumulator = 0f



    private val longPressRunnable = Runnable {

        if (!state.moved && !state.scrollActive) {

            if (isDragModeEnabled()) {

                state.dragActive = true
                emit(GestureEvent.DragStart)

            } else {

                emit(GestureEvent.ContextMenu)

            }


            state.longPressTriggered = true
        }

    }





    // =========================
    // ANDROID ADAPTER
    // =========================


    fun handle(event: MotionEvent): Boolean {

        when(event.actionMasked){

            MotionEvent.ACTION_DOWN ->
                onDown(event.x,event.y)


            MotionEvent.ACTION_MOVE ->
                onMove(event.x,event.y)


            MotionEvent.ACTION_UP,
            MotionEvent.ACTION_CANCEL ->
                onUp()

        }

        return true
    }





    // =========================
    // POINTER LOGIC
    // =========================



    fun onDown(
        x:Float,
        y:Float
    ){

        state.downTime =
            System.currentTimeMillis()


        state.startX = x
        state.startY = y

        state.lastX = x
        state.lastY = y


        state.moved = false
        state.longPressTriggered = false
        state.scrollActive = false


        scrollAccumulator = 0f



        handler.postDelayed(
            longPressRunnable,
            GestureConfig.LONG_PRESS_MS
        )

    }







    fun onMove(
        x:Float,
        y:Float
    ){

        val dx =
            x - state.lastX


        val dy =
            y - state.lastY



        /*
         * Если идет scroll,
         * обычное движение мыши блокируем
         */

        if(state.scrollActive){

            state.lastX = x
            state.lastY = y

            return
        }




        if(
            abs(x-state.startX)
            > GestureConfig.MOVE_THRESHOLD ||
            abs(y-state.startY)
            > GestureConfig.MOVE_THRESHOLD
        ){

            state.moved = true

        }




        state.lastX=x
        state.lastY=y




        if(state.dragActive){

            emit(
                GestureEvent.DragMove(
                    dx,
                    dy
                )
            )

        }
        else{

            emit(
                GestureEvent.Move(
                    dx,
                    dy
                )
            )

        }

    }








    fun onUp(){

        handler.removeCallbacks(
            longPressRunnable
        )


        val now =
            System.currentTimeMillis()


        val pressTime =
            now - state.downTime






        if(state.dragActive){

            if(
                !state.moved &&
                pressTime < GestureConfig.LONG_PRESS_MS
            ){

                emit(
                    GestureEvent.DragEnd
                )


                state.dragActive=false
                state.lastTapTime=0L

            }


            return
        }







        if(state.scrollActive){

            state.scrollActive=false
            scrollAccumulator=0f

            state.resetTap()

            return
        }








        if(
            !state.moved &&
            pressTime < GestureConfig.LONG_PRESS_MS
        ){



            if(
                now - state.lastTapTime
                <= GestureConfig.DOUBLE_TAP_MS
            ){

                emit(
                    GestureEvent.DoubleTap
                )

                state.lastTapTime=0L

            }
            else{


                emit(
                    GestureEvent.Tap
                )


                state.lastTapTime=now

            }

        }

    }








    // =========================
    // TWO FINGER SCROLL
    // =========================



    fun onScrollStart(
        x:Float,
        y:Float
    ){

        cancelLongPress()


        state.scrollActive=true



        /*
         * синхронизация координат,
         * чтобы после двух пальцев
         * не был скачок курсора
         */

        state.lastX=x
        state.lastY=y

        state.startX=x
        state.startY=y


        state.moved=false


        scrollAccumulator=0f

    }








    fun onScroll(
        dy:Float
    ){

        val value =
            dy * SCROLL_SENSITIVITY



        scrollAccumulator += value



        if(
            abs(scrollAccumulator)
            >= SCROLL_DEAD_ZONE
        ){


            emit(
                GestureEvent.Scroll(
                    scrollAccumulator
                )
            )


            scrollAccumulator=0f

        }

    }








    fun cancelLongPress(){

        handler.removeCallbacks(
            longPressRunnable
        )


        state.longPressTriggered=false

    }

}