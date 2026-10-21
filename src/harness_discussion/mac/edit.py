"""In-place editing on macOS: read the selection with its app and window, and replace it by pasting.

There is no AX setter that keeps the app's own undo, so text goes in through the pasteboard and Cmd+V,
and the user's pasteboard is put back afterwards.
"""
import os
import time

import AppKit
import Quartz
from ApplicationServices import (AXUIElementCopyAttributeValue, AXUIElementCreateApplication,
                                 AXUIElementIsAttributeSettable, AXUIElementSetAttributeValue, AXValueCreate,
                                 AXValueGetValue, kAXErrorSuccess, kAXValueCFRangeType)
from CoreFoundation import CFRangeMake

from .. import edit_logic
from ..edit_logic import Context
from . import pasteboard, permission, selection

KEY_V, KEY_LEFT, KEY_RIGHT = 9, 123, 124
EDITABLE_ROLES = {"AXTextArea", "AXTextField", "AXComboBox", "AXSearchField"}
PASTE_WAIT_S = 0.15
NEWLINE = "\n"


def _attr(element, name):
    err, value = AXUIElementCopyAttributeValue(element, name, None)
    return value if err == kAXErrorSuccess else None


def _focused(pid):
    return _attr(AXUIElementCreateApplication(pid), "AXFocusedUIElement")


def _window_number(pid):
    """The frontmost on-screen window of `pid`, or 0."""
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID)
    for info in infos or []:
        if info.get("kCGWindowOwnerPID") == pid and info.get("kCGWindowLayer") == 0:
            return int(info.get("kCGWindowNumber", 0))
    return 0


def _editable(element):
    if element is None:
        return False
    if _attr(element, "AXRole") in EDITABLE_ROLES:
        return True
    err, settable = AXUIElementIsAttributeSettable(element, "AXValue", None)
    return err == kAXErrorSuccess and bool(settable)


def _frontmost_pid():
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return app.processIdentifier() if app is not None else None


def capture(clipboard_fallback=False):
    """The selection with its app and window, or None when nothing is readable (or it is our own window)."""
    if not permission.trusted():
        return None
    pid = _frontmost_pid()
    if pid is None or pid == os.getpid():
        return None
    selection._expose(pid)
    element = _focused(pid)
    secure = selection.secure_input() or (element is not None and selection.SECURE in (
        _attr(element, "AXRole"), _attr(element, "AXSubrole")))
    text = ""
    if not secure:
        found, _ = selection._via_ax(pid)
        text = found or ""
        if not text and clipboard_fallback:
            text = pasteboard.copy_selection()
    if _frontmost_pid() != pid:
        return None
    return Context(text, pid, _window_number(pid), _editable(element), secure)


def same_context(ctx):
    return edit_logic.same_context(ctx, capture(clipboard_fallback=True))


def _key(code, flags=0):
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(event, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _paste(text):
    """Pastes `text` and puts the pasteboard back if nothing else wrote to it meanwhile."""
    if not pasteboard.safe_to_borrow(pasteboard.types()):
        return False
    board = AppKit.NSPasteboard.generalPasteboard()
    with pasteboard._borrow:
        saved = pasteboard.snapshot()
        board.clearContents()
        board.setString_forType_(text, AppKit.NSPasteboardTypeString)
        count = board.changeCount()
        _key(KEY_V, Quartz.kCGEventFlagMaskCommand)
        time.sleep(PASTE_WAIT_S)
        if edit_logic.restore_clipboard(board.changeCount(), count):
            pasteboard.restore(saved)
    return True


def _same_target(ctx):
    """With a captured Context, the same app and window still has an editable, non-secure field focused."""
    if ctx is None:
        return True
    now = capture(False)
    return now is not None and (now.app, now.window) == (ctx.app, ctx.window) and now.editable and not now.secure


def replace(text, ctx=None):
    """Replaces the selection. False if the target moved or the app ignored the paste (same text still selected)."""
    if not _same_target(ctx):
        return False
    pid = _frontmost_pid()
    before = _attr(_focused(pid), "AXSelectedText") if pid else None
    if not _paste(text):
        return False
    after = _attr(_focused(pid), "AXSelectedText") if pid else None
    return not (before and after and str(after) == str(before) and str(before) != text)


def type_at_caret(text, ctx=None):
    return _same_target(ctx) and _paste(text)


def _range(element):
    value = _attr(element, "AXSelectedTextRange")
    if value is None:
        return None
    ok, rng = AXValueGetValue(value, kAXValueCFRangeType, None)
    return rng if ok else None


def select_back(n, ctx=None):
    """Selects the `n` UTF-16 units before the caret. AX range first, Shift+Left × n as the fallback."""
    if not _same_target(ctx):
        return False
    pid = _frontmost_pid()
    element = _focused(pid) if pid else None
    rng = _range(element) if element is not None else None
    if rng is not None and rng[0] >= n:
        value = AXValueCreate(kAXValueCFRangeType, CFRangeMake(rng[0] - n, n))
        if AXUIElementSetAttributeValue(element, "AXSelectedTextRange", value) == kAXErrorSuccess:
            return True
    for _ in range(n):
        _key(KEY_LEFT, Quartz.kCGEventFlagMaskShift)
    return True


def collapse():
    """Moves the caret to the end of the selection."""
    pid = _frontmost_pid()
    element = _focused(pid) if pid else None
    rng = _range(element) if element is not None else None
    if rng is not None:
        value = AXValueCreate(kAXValueCFRangeType, CFRangeMake(rng[0] + rng[1], 0))
        if AXUIElementSetAttributeValue(element, "AXSelectedTextRange", value) == kAXErrorSuccess:
            return
    _key(KEY_RIGHT)
