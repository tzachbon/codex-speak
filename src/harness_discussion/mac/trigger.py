"""Turns global mouse input into "text may have just been selected here" events.

Coordinates are top-left based on the main screen, in points, the way the core and popup use them.
"""
import time

import AppKit

from .. import hotkeys
from ..clicks import Clicks

MASK = AppKit.NSEventMaskLeftMouseDown | AppKit.NSEventMaskLeftMouseUp


def top_left(point):
    height = AppKit.NSScreen.screens()[0].frame().size.height
    return point.x, height - point.y


class SelectionTrigger:
    """Handlers run on the main thread, so they must only hand work off, never block."""

    def __init__(self, on_selection, on_press):
        self.on_selection, self.on_press = on_selection, on_press
        self._clicks = Clicks(AppKit.NSEvent.doubleClickInterval())
        self._monitors = []

    def start(self):
        if self._monitors:
            return
        self._monitors.append(AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(MASK, self._event))

        def local(event):  # clicks on our own windows, which the global monitor never sees
            self._event(event)
            return event
        self._monitors.append(AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(MASK, local))

    def stop(self):
        for monitor in self._monitors:
            AppKit.NSEvent.removeMonitor_(monitor)
        self._monitors = []

    def _event(self, event):
        x, y = top_left(AppKit.NSEvent.mouseLocation())
        if event.type() == AppKit.NSEventTypeLeftMouseDown:
            self._clicks.down(x, y)
            self.on_press(x, y)
        elif self._clicks.up(x, y, time.monotonic()) and event.window() is None:
            self.on_selection(x, y)  # a drag or multi-click in another app


FLAGS = {"ctrl": AppKit.NSEventModifierFlagControl, "alt": AppKit.NSEventModifierFlagOption,
         "shift": AppKit.NSEventModifierFlagShift, "cmd": AppKit.NSEventModifierFlagCommand}
# ANSI key codes, so the shortcut follows the physical key under any keyboard layout (Hebrew, Russian...)
KEY_CODES = {0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x", 8: "c", 9: "v", 11: "b", 12: "q",
             13: "w", 14: "e", 15: "r", 16: "y", 17: "t", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5",
             25: "9", 26: "7", 28: "8", 29: "0", 31: "o", 32: "u", 34: "i", 35: "p", 37: "l", 38: "j", 40: "k",
             45: "n", 46: "m", 122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6", 98: "f7",
             100: "f8", 101: "f9", 109: "f10", 103: "f11", 111: "f12"}


def event_spec(event):
    """The hotkeys string for a key-down event, or None for a key or combination a shortcut can't use."""
    key = KEY_CODES.get(event.keyCode())
    flags = event.modifierFlags()
    return key and hotkeys.spec({name for name, flag in FLAGS.items() if flags & flag}, key)


class HotKey:
    """Watches key-downs for one shortcut. In another app it can't swallow the key, so that app sees it too.
    With `on_release`, it also reports when the key or one of its modifiers comes up, for hold shortcuts."""

    def __init__(self, spec, on_hotkey, on_release=None):
        self.keys, self.on_hotkey = hotkeys.parse(spec), on_hotkey  # parsed, so modifier order doesn't matter
        self.on_release, self._held = on_release, None
        mask = AppKit.NSEventMaskKeyDown
        if on_release:
            mask |= AppKit.NSEventMaskKeyUp | AppKit.NSEventMaskFlagsChanged
        self._monitors = [AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self._event)]

        def local(event):  # keys while one of our windows is active, which the global monitor never sees
            self._event(event)
            return event
        self._monitors.append(AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, local))

    def _event(self, event):
        kind = event.type()
        if kind == AppKit.NSEventTypeKeyDown:
            if not event.isARepeat() and hotkeys.parse(event_spec(event)) == self.keys:
                self._held = event.keyCode() if self.on_release else None
                self.on_hotkey()
        elif self._held is not None:
            flags = event.modifierFlags()
            mods_down = all(flags & FLAGS[m] for m in self.keys[0])
            if (kind == AppKit.NSEventTypeKeyUp and event.keyCode() == self._held) or not mods_down:
                self._held = None
                self.on_release()

    def stop(self):
        for monitor in self._monitors:
            AppKit.NSEvent.removeMonitor_(monitor)
        self._monitors = []
