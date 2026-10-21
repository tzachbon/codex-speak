"""Watches Esc while the bar, the toast, or a rewrite is showing. Our panels never become key, so they never get keys.

A global monitor can't swallow the key, so Esc also reaches the frontmost app.
"""
import AppKit

ESC = 53


class EscWatcher:
    def __init__(self, on_escape):
        self.on_escape, self._monitors = on_escape, []

    @property
    def active(self):
        return bool(self._monitors)

    def start(self):
        if self._monitors:
            return

        def global_(event):
            if event.keyCode() == ESC and not event.isARepeat():
                self.on_escape()

        def local(event):
            global_(event)
            return event
        self._monitors = [
            AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(AppKit.NSEventMaskKeyDown, global_),
            AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(AppKit.NSEventMaskKeyDown, local)]

    def stop(self):
        for monitor in self._monitors:
            AppKit.NSEvent.removeMonitor_(monitor)
        self._monitors = []
