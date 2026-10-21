"""Writer toast and Review panel on real Tk, without clipboard, keys, or models."""
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

import time
import tkinter as tk
from unittest.mock import patch

from harness_discussion.win import review as win_review, toast as win_toast

def labels(widget):
    """Every label under widget, in creation order."""
    out = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            out.append(child)
        out += labels(child)
    return out

def click(root, widget, text):
    """Presses and releases the mouse on the visible label with this text, as a user would."""
    root.update()
    label = next(lbl for lbl in labels(widget) if lbl["text"] == text and lbl.winfo_viewable())
    x, y = label.winfo_rootx() + 2, label.winfo_rooty() + 2
    label.event_generate("<ButtonPress-1>", rootx=x, rooty=y, x=2, y=2)
    label.event_generate("<ButtonRelease-1>", rootx=x, rooty=y, x=2, y=2)
    root.update()

def pump(root, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)

class Base(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)

class ToastTest(Base):
    def make(self):
        self.actions = []
        toast = win_toast.Toast(self.root, self.actions.append)
        self.addCleanup(toast.destroy)
        return toast

    def test_shows_message_and_reports_each_action(self):
        toast = self.make()
        self.assertFalse(toast.visible)
        toast.show("✓ Rewritten · Message · Cursor", x=200, y=200)
        self.root.update()
        self.assertTrue(toast.visible)
        texts = [lbl["text"] for lbl in labels(toast.win)]
        self.assertIn("✓ Rewritten · Message · Cursor", texts)
        for name in ("Undo", "Review", "Mode"):
            self.assertIn(name, texts)
        for name in ("Undo", "Review", "Mode"):
            click(self.root, toast.win, name)
        self.assertEqual(self.actions, ["undo", "review", "mode"])

    def test_error_toast_offers_copy_only(self):
        toast = self.make()
        toast.show("Text changed. Copy result?", actions=("copy",), x=200, y=200)
        self.root.update()
        shown = [lbl["text"] for lbl in labels(toast.win) if lbl.winfo_viewable()]
        self.assertEqual(shown[1:], ["Copy"])
        click(self.root, toast.win, "Copy")
        self.assertEqual(self.actions, ["copy"])

    def test_auto_hides_unless_hovered_and_each_show_restarts_the_timer(self):
        toast = self.make()
        with patch.object(win_toast, "HIDE_MS", 150):
            toast.show("one", x=200, y=200)
            pump(self.root, 0.1)
            toast.show("two", x=200, y=200)  # restarts the countdown
            pump(self.root, 0.1)
            self.assertTrue(toast.visible)
            pump(self.root, 0.15)
            self.assertFalse(toast.visible)

            toast.show("three", x=200, y=200)
            toast.win.event_generate("<Enter>")
            pump(self.root, 0.3)
            self.assertTrue(toast.visible, "hovering pauses the auto-hide")
            toast.win.event_generate("<Leave>")
            pump(self.root, 0.3)
            self.assertFalse(toast.visible)

    def test_hide_and_destroy_cancel_the_timer(self):
        toast = self.make()
        with patch.object(win_toast, "HIDE_MS", 50):
            toast.show("one", x=200, y=200)
            toast.hide()
            toast.destroy()
            pump(self.root, 0.15)  # a pending hide on a destroyed window would raise TclError here
        self.assertFalse(toast.visible)

    def test_updating_a_hovered_toast_keeps_auto_hide_paused(self):
        toast = self.make()
        with patch.object(win_toast, "HIDE_MS", 50):
            toast.show("one", x=200, y=200)
            self.root.update()
            toast.win.event_generate("<Enter>")
            toast.show("two", x=200, y=200)
            pump(self.root, 0.15)
            self.assertTrue(toast.visible)

OLD = "hey team, the deploy broke cause the env var wasnt set"
NEW = "Hi team, the deploy failed because the env var wasn't set"

class ReviewTest(Base):
    def make(self):
        self.calls = []
        review = win_review.Review(self.root, on_replace=lambda t: self.calls.append(("replace", t)),
                                   on_copy=lambda t: self.calls.append(("copy", t)),
                                   on_rewrite=lambda t: self.calls.append(("rewrite", t)))
        self.addCleanup(review.destroy)
        return review

    def test_shows_both_sides_and_buttons_pass_the_result(self):
        review = self.make()
        self.assertFalse(review.visible)
        review.show(OLD, NEW)
        self.root.update()
        self.assertTrue(review.visible)
        self.assertEqual(review.left.get("1.0", "end-1c"), OLD)
        self.assertEqual(review.right.get("1.0", "end-1c"), NEW)
        for name in ("Rewrite again", "Copy", "Replace"):
            click(self.root, review.win, name)
        self.assertEqual(self.calls, [("rewrite", NEW), ("copy", NEW), ("replace", NEW)])

    def test_clicking_a_change_restores_just_that_change(self):
        review = self.make()
        review.show(OLD, NEW)
        self.root.update()
        start = review.right.search("failed", "1.0")
        x, y, _w, _h = review.right.bbox(f"{start}+1c")
        review.right.event_generate("<Motion>", x=x, y=y)  # tag bindings follow the pointer's "current" mark
        review.right.event_generate("<Button-1>", x=x, y=y)
        self.root.update()
        restored = "Hi team, the deploy broke because the env var wasn't set"
        self.assertEqual(review.headings[1]["text"], "Rewrite · 3 changes")
        self.assertEqual(review.right.get("1.0", "end-1c"), restored)
        self.assertEqual(review.left.get("1.0", "end-1c"), OLD)
        click(self.root, review.win, "Copy")
        self.assertEqual(self.calls, [("copy", restored)])
        review.show(OLD, NEW)  # a new review starts with every change applied
        self.assertEqual(review.right.get("1.0", "end-1c"), NEW)

    def test_replace_is_disabled_when_the_context_is_gone(self):
        review = self.make()
        review.show(OLD, NEW, can_replace=False)
        click(self.root, review.win, "Replace")
        click(self.root, review.win, "Rewrite again")
        self.assertEqual(self.calls, [])
        review.set_can_replace(True)
        click(self.root, review.win, "Replace")
        self.assertEqual(self.calls, [("replace", NEW)])
        review.set_can_replace(False)
        click(self.root, review.win, "Replace")
        click(self.root, review.win, "Copy")
        self.assertEqual(self.calls, [("replace", NEW), ("copy", NEW)])
        review.hide()
        self.assertFalse(review.visible)

if __name__ == "__main__":
    unittest.main()
