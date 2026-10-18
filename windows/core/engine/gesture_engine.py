import time


class GestureEngine:

    def __init__(self, backend):

        self.backend = backend

        self.dragging = False

        # накопление дробного скролла
        self._scroll_accum = 0.0


        # чувствительность
        self.SCROLL_SPEED = 1.7



    # ===== MOVE =====


    def move(self, dx: float, dy: float):

        self.backend.move(dx, dy)



    # ===== SCROLL =====


    def scroll(self, dy: float):

        print("SCROLL:", dy)


        # усиливаем/ослабляем скорость
        self._scroll_accum += (
            dy * self.SCROLL_SPEED
        )


        #
        # backend обычно умеет только
        # целые шаги колеса
        #
        while abs(self._scroll_accum) >= 1:


            step = (
                1
                if self._scroll_accum > 0
                else -1
            )


            self.backend.scroll(step)


            self._scroll_accum -= step






    # ===== CLICK =====


    def tap(self):

        self.backend.click("left")



    def double_tap(self):

        self.backend.click("left")

        time.sleep(0.03)

        self.backend.click("left")



    def right_tap(self):

        self.backend.click("right")





    # ===== DRAG =====


    def drag_start(self):

        self.dragging = True

        self.backend.mouse_down("left")



    def drag_move(
        self,
        dx: float,
        dy: float
    ):

        if self.dragging:

            self.backend.drag(
                dx,
                dy
            )



    def drag_end(self):

        if self.dragging:

            try:
                self.backend.mouse_up("left")
            finally:
                self.dragging = False


    def cancel_drag(self):
        """Force-release the left mouse button if a drag/session is interrupted."""
        self.dragging = False

        # Always send mouse_up: after a broken input sequence, the OS button
        # state is what matters, even if the local flag is already false.
        self.backend.mouse_up("left")