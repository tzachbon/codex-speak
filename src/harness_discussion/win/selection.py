"""Reads the user's current text selection in whatever app has focus."""
import os

import uiautomation as uia

from .. import settings
from . import uia_thread

MAX_CHARS = 4000
TERMINALS = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow",
             "mintty", "PuTTY", "VirtualConsoleClass"}  # Ctrl+C means "interrupt" there
PASSWORD = object()
os.makedirs(settings.TEMP_DIR, exist_ok=True)
uia.Logger.SetLogFile(os.path.join(settings.TEMP_DIR, "uia.log"))  # default: cwd


def _via_uia():
    """Selected text, or "" when UIA can't tell (no text pattern, or apps like VS Code that hide it)."""
    def inspect():
        try:
            controls = _safe_controls()
            if controls is None or controls is PASSWORD:
                return PASSWORD
            for ctl in controls:
                pattern = ctl.GetPattern(uia.PatternId.TextPattern)
                if pattern:
                    return "".join(r.GetText(-1) for r in pattern.GetSelection())
        except Exception:
            return PASSWORD
        return ""
    result = uia_thread.run(inspect)
    return PASSWORD if result is None else result


def _safe_controls():
    controls, node = [], uia.GetFocusedControl()
    for _ in range(32):
        if node is None:
            return controls
        password = password_state(node)
        if password is None:
            return None
        if password:
            return PASSWORD
        controls.append(node)
        node = node.GetParentControl()
    return None


def password_state(control):
    # The wrapper's IsPassword substitutes False for unsupported metadata.
    value = control.Element.GetCurrentPropertyValueEx(uia.PropertyId.IsPasswordProperty, True)
    return value if type(value) is bool else None


def read(clipboard_fallback: bool = True) -> str:
    """Read accessible selection text. The shared clipboard flag is retained but cannot enable unsafe copying."""
    text = _via_uia()
    return "" if text is PASSWORD else text.strip()[:MAX_CHARS]
