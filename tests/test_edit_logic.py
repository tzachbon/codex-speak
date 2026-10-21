"""In-place edit logic with no platform: guards, UTF-16 lengths, and the undo sequence."""
import unittest

from harness_discussion import edit_logic
from harness_discussion.edit_logic import Context

CTX = Context("old", app=10, window=20, editable=True, secure=False)


class FakePlatform:
    def __init__(self, now):
        self.now, self.log = now, []

    def select_back(self, n):
        self.log.append(("select_back", n))
        return True

    def capture(self, clipboard_fallback):
        self.log.append(("capture",))
        return self.now

    def collapse(self):
        self.log.append(("collapse",))

    def replace(self, text):
        self.log.append(("replace", text))
        return True


class GuardTest(unittest.TestCase):
    def test_same_context(self):
        self.assertTrue(edit_logic.same_context(CTX, CTX))
        self.assertFalse(edit_logic.same_context(CTX, Context("old", 11, 20, True, False)))
        self.assertFalse(edit_logic.same_context(CTX, Context("old", 10, 21, True, False)))
        self.assertFalse(edit_logic.same_context(CTX, Context("new", 10, 20, True, False)))
        self.assertFalse(edit_logic.same_context(CTX, Context("", 10, 20, True, False)))
        self.assertFalse(edit_logic.same_context(CTX, None))

    def test_restore_is_skipped_when_the_clipboard_changed(self):
        self.assertTrue(edit_logic.restore_clipboard(7, 7))
        self.assertFalse(edit_logic.restore_clipboard(8, 7))

    def test_utf16_length(self):
        self.assertEqual(edit_logic.utf16_len("hi 👋"), 5)
        self.assertEqual(edit_logic.utf16_len("a\nb"), 3)
        self.assertEqual(edit_logic.utf16_len("a\nb\r\nc", newline="\r\n"), 7)


class UndoTest(unittest.TestCase):
    def test_undo_selects_checks_then_replaces(self):
        platform = FakePlatform(Context("new 👋", 10, 20, True, False))
        self.assertTrue(edit_logic.undo(platform, CTX, "old", "new 👋"))
        self.assertEqual(platform.log, [("select_back", 6), ("capture",), ("replace", "old")])

    def test_undo_stops_when_the_check_fails(self):
        platform = FakePlatform(Context("something else", 10, 20, True, False))
        self.assertFalse(edit_logic.undo(platform, CTX, "old", "new"))
        self.assertEqual(platform.log, [("select_back", 3), ("capture",), ("collapse",)])


if __name__ == "__main__":
    unittest.main()
