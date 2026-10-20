"""Turns global mouse input into "text may have just been selected here" events."""
import ctypes
import time

from pynput import keyboard, mouse

from .. import hotkeys
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


# Virtual-key codes, so the shortcut follows the physical key under any keyboard layout (Hebrew, Russian...)
VK = {**{k: ord(k.upper()) for k in "abcdefghijklmnopqrstuvwxyz0123456789"}, **{f"f{n}": 0x6F + n for n in range(1, 13)}}
MOD_KEYS = {"ctrl": (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r),
            "alt": (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr),
            "shift": (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r),
            "cmd": (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r)}


def _name(key):
    """A modifier's name, or the key's virtual-key code (function keys are Key members holding a KeyCode)."""
    for name, keys in MOD_KEYS.items():
        if key in keys:
            return name
    return getattr(key, "vk", None) or getattr(getattr(key, "value", None), "vk", None)


class HotKey:
    """Fires once every key of the shortcut is up, so a borrowed Ctrl+C isn't sent as Ctrl+Alt+C."""

    def __init__(self, spec, on_hotkey):
        mods, key = hotkeys.parse(spec)
        self.on_hotkey, self._keys, self._held, self._pending = on_hotkey, {*mods, VK[key]}, set(), False
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.start()

    def _press(self, key):
        self._held.add(_name(key))
        if self._held == self._keys:  # exactly the shortcut: Ctrl+Alt+Shift+R isn't Ctrl+Alt+R
            self._pending = True

    def _release(self, key):
        self._held.discard(_name(key))
        if self._pending and not self._held:
            self._pending = False
            self.on_hotkey()

    def stop(self):
        self._listener.stop()
