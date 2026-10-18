"""Turns global mouse input into "text may have just been selected here" events."""
import ctypes
import time

from pynput import mouse

from ..clicks import DRAG_PX, Clicks  # noqa: F401  DRAG_PX is part of this module's surface

MULTI_CLICK_S = ctypes.windll.user32.GetDoubleClickTime() / 1000


class SelectionTrigger:
    """Callbacks run on the hook thread, so they must only enqueue work, never block."""

    def __init__(self, on_selection, on_press):
        self.on_selection, self.on_press = on_selection, on_press
        self._clicks = Clicks(MULTI_CLICK_S)
        self._listener = mouse.Listener(on_click=self._click)

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()

    def _click(self, x, y, button, pressed):
        if button != mouse.Button.left:
            return
        if pressed:
            self._clicks.down(x, y)
            self.on_press(x, y)
            return
        if self._clicks.up(x, y, time.monotonic()):
            self.on_selection(x, y)
