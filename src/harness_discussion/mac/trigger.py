"""Turns global mouse input into "text may have just been selected here" events.

Coordinates are top-left based on the main screen, in points, the way the core and popup use them.
"""
import time

import AppKit

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
