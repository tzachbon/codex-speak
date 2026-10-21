"""Reads the user's current text selection in whatever app has focus."""
import ctypes
import os
import time

import uiautomation as uia

from .. import richtext, settings
from . import clipboard, uia_thread
from . import input as keys

MAX_CHARS = 4000
TERMINALS = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow",
             "mintty", "PuTTY", "VirtualConsoleClass"}  # Ctrl+C means "interrupt" there
WEB = {"Chrome_WidgetWin_1", "MozillaWindowClass"}  # Chrome, Edge, Electron apps, Firefox
PASSWORD = object()
ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
ctypes.windll.user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
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


def _foreground_class() -> str:
    cls = ctypes.create_unicode_buffer(64)
    ctypes.windll.user32.GetClassNameW(ctypes.windll.user32.GetForegroundWindow(), cls, 64)
    return cls.value


def _via_clipboard(html=False):
    """Borrows the clipboard for one Ctrl+C and puts every format back afterwards. With `html`: (text, HTML)."""
    if html:
        return _copy(True) or ("", "")
    return _copy(False)


def _copy(html):
    return uia_thread.run(_copy_on_worker, html) or ""


def _copy_on_worker(html):
    with clipboard.BORROW_LOCK:
        origin = _focus_identity()
        if not origin:
            return ""
        saved, seq = clipboard.snapshot_with_sequence()
        with clipboard.PreparedRestore(saved) as cleanup:
            if _focus_identity() != origin or clipboard.sequence() != seq:
                return ""
            if not keys.chord(ord("C")):
                return ""  # refused/partial input cannot establish ownership of a subsequent copy
            deadline = time.monotonic() + 0.3
            while clipboard.sequence() == seq and time.monotonic() < deadline:
                time.sleep(0.01)
            if clipboard.sequence() == seq:
                return ""
            time.sleep(0.03)
            copied = clipboard.sequence()
            if clipboard.owner_pid() != origin[0]:
                return ""  # a concurrent copy is not our selection and must not be overwritten
            try:
                if _focus_identity() != origin:
                    return ""
                result = clipboard.read_owned_selection(copied, origin[0], html)
                if result is None:
                    return ""
                text, copied = result
                return text
            finally:
                cleanup.apply(expected_sequence=copied)


def _focus_identity():
    """Check security before a fallback copy; never reads text or infers safety from a failed UIA call."""
    try:
        if _foreground_class() in TERMINALS:
            return None
        u32 = ctypes.windll.user32
        u32.GetForegroundWindow.restype = ctypes.c_void_p
        u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        hwnd, pid = u32.GetForegroundWindow(), ctypes.c_ulong()
        if not hwnd or not u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
            return None
        controls = _safe_controls()
        if not controls or controls is PASSWORD:
            return None
        identity = tuple(controls[0].GetRuntimeId())
        return (pid.value, hwnd, identity) if identity and hwnd == u32.GetForegroundWindow() else None
    except Exception:
        return None


def read(clipboard_fallback: bool = True) -> str:
    text = _via_uia()
    if text is PASSWORD:
        return ""
    if not text.strip() and clipboard_fallback:
        text = _via_clipboard()
    elif ("\n" in text and clipboard_fallback and not richtext.has_numbers(text)
          and _foreground_class() in WEB):
        # web pages draw list numbers with CSS: the selected text drops them, the copied HTML keeps them
        _, html = _via_clipboard(html=True)
        if "<ol" in html:
            text = richtext.html_to_text(html)
    return text.strip()[:MAX_CHARS]
