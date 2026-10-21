"""T4 gate helper: replace and undo in one app, checking the field and the clipboard. Mac only.

Usage: uv run python spikes/edit_gate.py [textedit|safari|chrome]
Prints only pass or fail per check. The browser targets are a local page with a <textarea>.
"""
import pathlib
import subprocess
import sys
import tempfile
import time

import AppKit

from harness_discussion import edit_logic
from harness_discussion.mac import edit

SAMPLE, FIXED, MARK = "i thinks we should of shiped it 👋", "I think we should have shipped it 👋", "clipboard-mark-42"
BROWSERS = {"safari": "Safari", "chrome": "Google Chrome"}
PAGE = ("<!doctype html><meta charset=utf-8><textarea id=t autofocus rows=4 cols=60></textarea>"
        f"<script>t.value={SAMPLE!r};t.focus();t.select()</script>")


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def select_all():
    osa('tell application "System Events" to keystroke "a" using command down')
    time.sleep(0.3)


def field_text():
    select_all()
    ctx = edit.capture(clipboard_fallback=False)
    return ctx.text if ctx else None


def open_target(target):
    if target == "textedit":
        osa(f'tell application "TextEdit" to activate\n'
            f'tell application "TextEdit" to make new document with properties {{text:"{SAMPLE}"}}')
        time.sleep(1)
        return lambda: osa('tell application "TextEdit" to close front document saving no')
    page = pathlib.Path(tempfile.mkdtemp()) / "gate.html"
    page.write_text(PAGE, encoding="utf-8")
    app = BROWSERS[target]
    subprocess.run(["open", "-a", app, str(page)], check=True)
    time.sleep(3)
    osa(f'tell application "{app}" to activate')
    time.sleep(0.5)
    osa('tell application "System Events" to keystroke tab')  # focus the field if the page didn't
    tab = "current tab" if target == "safari" else "active tab"
    return lambda: osa(f'tell application "{app}" to close {tab} of front window')


target = sys.argv[1] if len(sys.argv) > 1 else "textedit"
board = AppKit.NSPasteboard.generalPasteboard()
board.clearContents()
board.setString_forType_(MARK, AppKit.NSPasteboardTypeString)
close = open_target(target)
try:
    select_all()
    ctx = edit.capture(clipboard_fallback=False)
    print(target, "capture editable:", ctx and ctx.editable, "text matches:", ctx and ctx.text == SAMPLE)
    print("same_context:", bool(ctx) and edit.same_context(ctx))
    print("replace:", edit.replace(FIXED))
    time.sleep(0.3)
    print("clipboard kept:", board.stringForType_(AppKit.NSPasteboardTypeString) == MARK)
    print("undo:", edit_logic.undo(edit, ctx, SAMPLE, FIXED))
    time.sleep(0.3)
    print("field restored:", field_text() == SAMPLE)
    print("clipboard kept after undo:", board.stringForType_(AppKit.NSPasteboardTypeString) == MARK)
finally:
    close()
