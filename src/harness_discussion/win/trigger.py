"""Turns global mouse input into "text may have just been selected here" events."""
import ctypes
import threading
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


def _physical(key):
    return getattr(key, "vk", None) or getattr(getattr(key, "value", None), "vk", None) or key


class HotKey:
    """Fires once every key of the shortcut is up, so a borrowed Ctrl+C isn't sent as Ctrl+Alt+C.
    With on_release, fires at key-down instead and calls on_release once the chord is all up,
    for hold-to-act shortcuts like dictation."""

    def __init__(self, spec, on_hotkey, on_release=None):
        mods, key = hotkeys.parse(spec)
        self.on_hotkey, self.on_release, self._keys, self._held = on_hotkey, on_release, {*mods, VK[key]}, {}
        self._pending, self._armed = False, True  # armed blocks auto-repeat and a re-press during a partial release
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.start()

    def _press(self, key):
        self._held[_physical(key)] = _name(key)
        if not self._armed or set(self._held.values()) != self._keys:
            return
        if self.on_release is None:
            self._pending = True
            return
        self._armed = False
        self.on_hotkey()

    def _release(self, key):
        self._held.pop(_physical(key), None)
        if self._held:
            return
        if self._pending:
            self._pending = False
            self.on_hotkey()
        elif not self._armed:
            self._armed = True  # rearm only once everything is released
            self.on_release()

    def stop(self):
        self._listener.stop()


class Escape:
    """Temporary watcher. Callback only enqueues, suppress() is true for bar/rewrite activity."""
    def __init__(self, on_escape, suppress=lambda: True, autostart=True):
        self.on_escape, self.suppress = on_escape, suppress
        self._lock = threading.RLock()
        self._held, self._listener, self._generation = False, None, 0
        if autostart:
            self.start()

    @property
    def active(self):
        with self._lock:
            return self._listener is not None

    def start(self):
        with self._lock:
            if self._listener is not None:
                return
            self._generation += 1
            generation = self._generation
            self._held = False

            listener = None

            def event_filter(message, data):
                return self._filter(listener, generation, message, data)

            listener = keyboard.Listener(win32_event_filter=event_filter)
            self._listener = listener
            try:
                listener.start()
            except BaseException:
                self._listener = None
                self._generation += 1
                self._held = False
                try:
                    listener.stop()
                except BaseException:
                    pass
                raise

    def _filter(self, listener, generation, message, data):
        with self._lock:
            if self._listener is not listener or self._generation != generation:
                return False
            if data.vkCode != 27:
                return True
            if message in (0x100, 0x104):  # WM_KEYDOWN / WM_SYSKEYDOWN
                if not self._held:
                    self._held = True
                    self.on_escape()
            elif message in (0x101, 0x105):
                self._held = False
            if self._listener is not listener or self._generation != generation:
                return False
            suppress = self.suppress()
            if self._listener is not listener or self._generation != generation:
                return False
            if suppress:
                listener.suppress_event()
            return False

    def stop(self):
        with self._lock:
            listener = self._listener
            if listener is None:
                return
            self._listener = None
            self._generation += 1
            self._held = False
            listener.stop()
