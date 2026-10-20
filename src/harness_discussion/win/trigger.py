"""Turns global mouse input into "text may have just been selected here" events."""
import ctypes
import time

from pynput import keyboard, mouse

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


class HotKey:
    """Fires once every key of the shortcut is up, so a borrowed Ctrl+C isn't sent as Ctrl+Alt+C."""

    def __init__(self, spec, on_hotkey):
        self.on_hotkey, self._held, self._pending = on_hotkey, set(), False
        self._hotkey = keyboard.HotKey(keyboard.HotKey.parse(spec), self._activate)
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.start()

    def _activate(self):
        self._pending = True

    def _press(self, key):
        key = self._listener.canonical(key)
        self._held.add(key)
        self._hotkey.press(key)

    def _release(self, key):
        key = self._listener.canonical(key)
        self._held.discard(key)
        self._hotkey.release(key)
        if self._pending and not self._held:
            self._pending = False
            self.on_hotkey()

    def stop(self):
        self._listener.stop()
