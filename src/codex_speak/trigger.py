"""Turns global mouse input into "text may have just been selected here" events."""
import ctypes
import time

from pynput import mouse

DRAG_PX = 6
MULTI_CLICK_S = ctypes.windll.user32.GetDoubleClickTime() / 1000


class SelectionTrigger:
    """Callbacks run on the hook thread, so they must only enqueue work, never block."""

    def __init__(self, on_selection, on_press):
        self.on_selection, self.on_press = on_selection, on_press
        self._down, self._last = (0, 0), (0, 0, 0.0)
        self._listener = mouse.Listener(on_click=self._click)

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()

    def _click(self, x, y, button, pressed):
        if button != mouse.Button.left:
            return
        if pressed:
            self._down = (x, y)
            self.on_press(x, y)
            return
        lx, ly, lt = self._last
        now = time.monotonic()
        self._last = (x, y, now)
        dragged = abs(x - self._down[0]) > DRAG_PX or abs(y - self._down[1]) > DRAG_PX
        multi = now - lt < MULTI_CLICK_S and abs(x - lx) <= 4 and abs(y - ly) <= 4
        if dragged or multi:
            self.on_selection(x, y)
