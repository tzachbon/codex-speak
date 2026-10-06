"""Reads the user's current text selection in whatever app has focus."""
import ctypes
import os
import tempfile
import time

import uiautomation as uia
from pynput.keyboard import Controller, Key

from . import clipboard

MAX_CHARS = 4000
TERMINALS = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}  # Ctrl+C means "interrupt" there
PASSWORD = object()
uia.Logger.SetLogFile(os.path.join(tempfile.gettempdir(), "select-to-tts-uia.log"))  # default: cwd


def _via_uia():
    """Selected text, or "" when UIA can't tell (no text pattern, or apps like VS Code that hide it)."""
    with uia.UIAutomationInitializerInThread():
        ctl = uia.GetFocusedControl()
        for _ in range(6):
            if ctl is None:
                break
            if ctl.IsPassword:
                return PASSWORD
            pattern = ctl.GetPattern(uia.PatternId.TextPattern)
            if pattern:
                return "".join(r.GetText(-1) for r in pattern.GetSelection())
            ctl = ctl.GetParentControl()
    return ""


def _via_clipboard() -> str:
    """Borrows the clipboard for one Ctrl+C and puts every format back afterwards."""
    cls = ctypes.create_unicode_buffer(64)
    ctypes.windll.user32.GetClassNameW(ctypes.windll.user32.GetForegroundWindow(), cls, 64)
    if cls.value in TERMINALS or not clipboard.safe_to_borrow(clipboard.formats()):
        return ""
    saved, seq = clipboard.snapshot(), clipboard.sequence()
    kb = Controller()
    with kb.pressed(Key.ctrl):
        kb.tap("c")
    deadline = time.monotonic() + 0.3
    while clipboard.sequence() == seq and time.monotonic() < deadline:
        time.sleep(0.01)
    if clipboard.sequence() == seq:
        return ""  # nothing was selected, nothing was copied
    time.sleep(0.03)  # let the app finish writing every format
    try:
        return clipboard.text()
    finally:
        clipboard.restore(saved)


def read(clipboard_fallback: bool = True) -> str:
    text = _via_uia()
    if text is PASSWORD:
        return ""
    if not text.strip() and clipboard_fallback:
        text = _via_clipboard()
    return text.strip()[:MAX_CHARS]
