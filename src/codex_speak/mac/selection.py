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


def _via_ax():
    element = _attr(_system, "AXFocusedUIElement")
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


def read(clipboard_fallback: bool = True) -> str:
    if not permission.trusted():
        return ""
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None or app.processIdentifier() == os.getpid():
        return ""
    _expose(app.processIdentifier())
    text = _via_ax()
    if text is None:
        return ""  # a password field
    if not text.strip() and clipboard_fallback and not secure_input():
        text = pasteboard.copy_selection()
    return text.strip()[:MAX_CHARS]
