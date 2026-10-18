"""Reads the current selection in the frontmost app through the Accessibility API."""
import ctypes
import os

import AppKit
from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateApplication,
                                 AXUIElementCreateSystemWide, AXUIElementSetAttributeValue,
                                 AXUIElementSetMessagingTimeout, kAXErrorSuccess)

from . import pasteboard, permission

MAX_CHARS = 4000
SECURE = "AXSecureTextField"
_system = AXUIElementCreateSystemWide()
AXUIElementSetMessagingTimeout(_system, 0.5)  # the default for every element: a hung app can't block reads
_manual = set()  # pids already asked to expose their accessibility tree
_carbon = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/Carbon.framework/Carbon")
_carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool


def secure_input() -> bool:
    """True while a password field anywhere has keyboard focus."""
    return _carbon.IsSecureEventInputEnabled()


def _attr(element, name):
    err, value = AXUIElementCopyAttributeValue(element, name, None)
    return value if err == kAXErrorSuccess else None


def _expose(pid):
    """Chromium and Electron apps build their accessibility tree only when asked."""
    if pid not in _manual:
        _manual.add(pid)
        AXUIElementSetAttributeValue(AXUIElementCreateApplication(pid), "AXManualAccessibility", True)


def _via_ax(pid):
    # The system-wide element often fails with kAXErrorCannotComplete. Asking the app works.
    element = _attr(AXUIElementCreateApplication(pid), "AXFocusedUIElement")
    for _ in range(6):
        if element is None:
            return ""
        if SECURE in (_attr(element, "AXRole"), _attr(element, "AXSubrole")):
            return None
        text = _attr(element, "AXSelectedText")
        if text:
            return str(text)
        element = _attr(element, "AXParent")
    return ""


def _frontmost_pid():
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.processIdentifier() if app is not None else None


def read(clipboard_fallback: bool = True) -> str:
    if not permission.trusted():
        return ""
    pid = _frontmost_pid()
    if pid is None or pid == os.getpid():
        return ""
    _expose(pid)
    text = _via_ax(pid)
    if text is None or _frontmost_pid() != pid:
        return ""  # a password field, or the user switched apps while we read
    if not text.strip() and clipboard_fallback and not secure_input():
        text = pasteboard.copy_selection()
    return text.strip()[:MAX_CHARS]
