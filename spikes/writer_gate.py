"""T6 gate helper: a real App on the Mac host rewrites a TextEdit selection, then Undo, then the rewrite shortcut.

Usage: uv run python spikes/writer_gate.py
Reads the real settings without saving them. Prints pass or fail per step and the toast messages.
"""
import subprocess
import time

import AppKit
import Quartz

from harness_discussion import core, hotkeys
from harness_discussion.mac import host as mac_host
from harness_discussion.mac.trigger import FLAGS, KEY_CODES

SAMPLE, MARK = "i thinks we should of shiped it", "clipboard-mark-42"


def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()


def text():
    return osa('tell application "TextEdit" to get text of front document')


def select_all():
    osa('tell application "TextEdit" to activate')
    osa('tell application "System Events" to keystroke "a" using command down')


def pump(app, seconds, until=lambda: False):
    """Keeps TextEdit in front: the T3 window that launched this script takes focus back otherwise."""
    end = time.monotonic() + seconds
    textedit = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.TextEdit")
    while time.monotonic() < end and not until():
        front = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        if textedit and front.bundleIdentifier() != "com.apple.TextEdit":
            textedit[0].activateWithOptions_(0)
        AppKit.NSRunLoop.currentRunLoop().runUntilDate_(AppKit.NSDate.dateWithTimeIntervalSinceNow_(0.05))
        app.pump()


def press(spec):
    mods, key = hotkeys.parse(spec)
    code = next(c for c, k in KEY_CODES.items() if k == key)
    flags = 0
    for m in mods:
        flags |= {"cmd": Quartz.kCGEventFlagMaskCommand, "alt": Quartz.kCGEventFlagMaskAlternate,
                  "ctrl": Quartz.kCGEventFlagMaskControl, "shift": Quartz.kCGEventFlagMaskShift}[m]
    for down in (True, False):
        e = Quartz.CGEventCreateKeyboardEvent(None, code, down)
        Quartz.CGEventSetFlags(e, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)


board = AppKit.NSPasteboard.generalPasteboard()
board.clearContents()
board.setString_forType_(MARK, AppKit.NSPasteboardTypeString)
host = mac_host.MacHost()
app = core.App(host)
osa(f'tell application "TextEdit" to make new document with properties {{text:"{SAMPLE}"}}')
try:
    select_all()
    pump(app, 0.8)
    app.rewrite_selection("Fix errors")
    pump(app, 60, lambda: not app.rewriting)
    pump(app, 0.5)
    fixed = text()
    print("toast:", app.toast.message)
    print("rewritten in place:", fixed != SAMPLE, repr(fixed))
    print("clipboard kept:", board.stringForType_(AppKit.NSPasteboardTypeString) == MARK)
    undo = next(b for b in app.toast.actions if "Undo" in str(b.attributedTitle().string()))
    undo.performClick_(None)
    pump(app, 1)
    print("undo restored:", text() == SAMPLE, "toast:", app.toast.message)
    select_all()
    pump(app, 0.8)
    press(app.cfg["rewrite_hotkey"])
    pump(app, 2, lambda: app.rewriting)
    print("shortcut started a rewrite:", app.rewriting)
    pump(app, 60, lambda: not app.rewriting)
    pump(app, 0.5)
    print("shortcut rewrote:", text() != SAMPLE, "toast:", app.toast.message)
    print("clipboard kept:", board.stringForType_(AppKit.NSPasteboardTypeString) == MARK)
finally:
    osa('tell application "TextEdit" to close front document saving no')
    app._close_writer()
    AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(host.item)
