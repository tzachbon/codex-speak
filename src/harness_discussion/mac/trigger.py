"""Turns global mouse input into "text may have just been selected here" events.

Coordinates are top-left based on the main screen, in points, the way the core and popup use them.
"""
import time

import AppKit
import Quartz

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
# keys that type no character, so the layout can't name them
SPECIAL = {36: "↩", 48: "⇥", 49: "Space", 51: "⌫", 53: "⎋", 71: "⌧", 76: "⌤", 114: "Help", 115: "↖",
           116: "⇞", 117: "⌦", 119: "↘", 121: "⇟", 123: "←", 124: "→", 125: "↓", 126: "↑",
           105: "F13", 107: "F14", 113: "F15", 106: "F16", 64: "F17", 79: "F18", 80: "F19", 90: "F20"}
KEYPAD = {65, 67, 69, 75, 78, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92}  # type the same as the main keys


def event_mods(event):
    flags = event.modifierFlags()
    return {name for name, flag in FLAGS.items() if flags & flag}


def event_spec(event):
    """The hotkeys string for a key-down event: letters, digits and F1-F12 by name, any other key by its code."""
    code = event.keyCode()
    return hotkeys.spec(event_mods(event), KEY_CODES.get(code) or f"key_{code}")


def _typed(code):
    """What the current keyboard layout types for a key, unmodified; "" when macOS can't say."""
    event = AppKit.NSEvent.eventWithCGEvent_(Quartz.CGEventCreateKeyboardEvent(None, code, True))
    return event.charactersIgnoringModifiers() if event else ""


def key_name(code):
    """A fixed name for keys that type no character, else what the current layout types."""
    if code in SPECIAL:
        return SPECIAL[code]
    text = _typed(code)
    if not text or not text.isprintable():
        return f"Key {code}"
    return ("Keypad " if code in KEYPAD else "") + text.upper()


class HotKey:
    """Watches key-downs for one shortcut. In another app it can't swallow the key, so that app sees it too.
    With `on_release`, it also reports when the key or one of its modifiers comes up, for hold shortcuts."""

    def __init__(self, spec, on_hotkey, on_release=None):
        self.keys, self.on_hotkey = hotkeys.parse(spec), on_hotkey  # parsed, so modifier order doesn't matter
        self.on_release, self._held, self._tap, self._spoiled = on_release, None, False, False
        mask = AppKit.NSEventMaskKeyDown
        if on_release or self.keys[1] is None:
            mask |= AppKit.NSEventMaskKeyUp | AppKit.NSEventMaskFlagsChanged
        self._monitors = [AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self._event)]

        def local(event):  # keys while one of our windows is active, which the global monitor never sees
            self._event(event)
            return event
        self._monitors.append(AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, local))

    def _event(self, event):
        kind = event.type()
        if self.keys[1] is None:
            return self._modifiers_only(event, kind)
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

    def _modifiers_only(self, event, kind):
        """A tap fires once the chord is let go with no other key pressed, so ⌃⌥R doesn't also fire ⌃⌥."""
        if kind == AppKit.NSEventTypeKeyDown:
            if event_mods(event) & self.keys[0]:  # typing before the chord starts doesn't cancel it
                self._tap, self._spoiled = False, True
            return
        if kind != AppKit.NSEventTypeFlagsChanged:
            return
        mods, chord = frozenset(event_mods(event)), self.keys[0]
        if not mods >= chord:  # the chord ended
            if self._held is not None:
                self._held = None
                self.on_release()
            elif self._tap:
                self.on_hotkey()
            self._tap = self._spoiled = False
        elif self.on_release is not None:
            if self._held is None:
                self._held = True
                self.on_hotkey()
        elif mods == chord and not self._spoiled:
            self._tap = True
        else:  # an extra modifier joined, so this hold is no longer a tap of the chord
            self._tap, self._spoiled = False, True

    def stop(self):
        for monitor in self._monitors:
            AppKit.NSEvent.removeMonitor_(monitor)
        self._monitors = []
