"""Opt-in real UIA/paste check in a disposable Win32 fixture, never an existing user document.

Run with WRITER_NATIVE_CHECK=1. The helper owns its windows, and the prior clipboard is restored
only while the test's sentinel is still current. This is not the Notepad/Slack/Edge matrix.
"""
import os
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

import ctypes
import json
import subprocess
import time
from ctypes import wintypes
from unittest.mock import patch

from harness_discussion.win import clipboard, edit

HELPER = r'''
import ctypes,json,os
from ctypes import wintypes
from harness_discussion.win.clipboard import u32
u32.SetFocus.argtypes=[wintypes.HWND]
u32.SetForegroundWindow.argtypes=[wintypes.HWND]
u32.CreateWindowExW.restype=wintypes.HWND
u32.GetMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT]
u32.DispatchMessageW.argtypes=[ctypes.POINTER(wintypes.MSG)]
u32.TranslateMessage.argtypes=[ctypes.POINTER(wintypes.MSG)]
parent=u32.CreateWindowExW(0,'STATIC','Writer disposable native fixture',0x10cf0000,
                         100,100,640,240,None,None,None,None)
first=u32.CreateWindowExW(0,'EDIT','Left old right',0x50810004,12,12,600,70,parent,None,None,None)
password=u32.CreateWindowExW(0,'EDIT','synthetic password',0x50810020,12,100,600,30,parent,None,None,None)
assert parent and first and password
u32.ShowWindow(parent,5)
u32.SetForegroundWindow(parent)
u32.SetFocus(first)
print(json.dumps({'window':parent,'edit':first,'password':password,'thread':ctypes.windll.kernel32.GetCurrentThreadId()}),flush=True)
message=wintypes.MSG()
while u32.GetMessageW(ctypes.byref(message),None,0,0)>0:
    if message.message==0x8001:
        u32.SetForegroundWindow(parent)
        u32.SetFocus(message.wParam)
    else:
        u32.TranslateMessage(ctypes.byref(message))
        u32.DispatchMessageW(ctypes.byref(message))
'''


@unittest.skipUnless(os.environ.get("WRITER_NATIVE_CHECK") == "1", "Explicit owned-window native check")
class NativeEdit(unittest.TestCase):
    def test_replace_clipboard_preservation_undo_and_password_refusal(self):
        u32 = ctypes.windll.user32
        u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        u32.SendMessageW.restype = ctypes.c_ssize_t
        u32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        try:
            original, initial_sequence = clipboard.snapshot_with_sequence()
        except OSError:
            self.skipTest("Current clipboard cannot be safely borrowed")
        helper = subprocess.Popen([sys.executable, "-c", HELPER], stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        self.addCleanup(helper.stdout.close)
        def stop():
            if helper.poll() is None:
                helper.terminate()
            helper.wait(timeout=5)
        self.addCleanup(stop)
        data = json.loads(helper.stdout.readline())
        def focus(handle):
            u32.PostThreadMessageW(data["thread"], 0x8001, handle, 0)
            deadline = time.monotonic() + 30
            while u32.GetForegroundWindow() != data["window"] and time.monotonic() < deadline:
                time.sleep(0.1)
            self.assertEqual(u32.GetForegroundWindow(), data["window"], "Refuse input outside our own fixture")
        focus(data["edit"])
        u32.SendMessageW(data["edit"], 0x00B1, 5, 8)
        context = edit.capture(False)
        self.assertIsNotNone(context)
        self.assertEqual((context.app, context.window, context.text), (helper.pid, data["window"], "old"))
        self.assertTrue(context.editable)
        original_restore, last_owned = clipboard.restore, [None]
        def track_restore(*args, **kwargs):
            result = original_restore(*args, **kwargs)
            if result is not None:
                last_owned[0] = result
            return result
        tracking = patch.object(clipboard, "restore", side_effect=track_restore)
        tracking.start()
        self.addCleanup(tracking.stop)
        sentinel = "Writer native clipboard sentinel\0".encode("utf-16-le")
        owned_sequence = clipboard.restore([(13, sentinel)], expected_sequence=initial_sequence)
        self.assertIsNotNone(owned_sequence, "Clipboard changed before the test, refuse borrowing")
        try:
            saved = dict(clipboard.snapshot())
            self.assertTrue(edit.replace("new", context))
            self.assertEqual(dict(clipboard.snapshot()), saved)
            self.assertTrue(edit.select_back(3, context))
            selected = edit.capture(False)
            self.assertEqual(selected.text, "new")
            self.assertTrue(edit.replace("old", selected))
            self.assertEqual(dict(clipboard.snapshot()), saved)
            focus(data["password"])
            secure = edit.capture(False)
            self.assertTrue(secure.secure)
            self.assertEqual(secure.text, "")
            self.assertFalse(edit.replace("must not paste", secure))
        finally:
            # A concurrent user copy has priority over restoring the test's old snapshot.
            if last_owned[0] is not None:
                original_restore(original, expected_sequence=last_owned[0])


if __name__ == "__main__":
    unittest.main()
