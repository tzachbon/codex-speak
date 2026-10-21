"""In-place edit logic with no platform: guards, UTF-16 lengths, and the undo sequence."""
import unittest

from harness_discussion import edit_logic
from harness_discussion.edit_logic import Context

CTX = Context("old", app=10, window=20, editable=True, secure=False)


class FakePlatform:
    def __init__(self, now):
        self.now, self.log, self.ctxs = now, [], []

    def select_back(self, n, ctx):
        self.log.append(("select_back", n))
        self.ctxs.append(ctx)
        return True

    def capture(self, clipboard_fallback):
        self.log.append(("capture",))
        return self.now

    def collapse(self):
        self.log.append(("collapse",))

    def replace(self, text, ctx):
        self.log.append(("replace", text))
        self.ctxs.append(ctx)
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
        self.assertEqual(platform.ctxs, [CTX, platform.now])  # select within the paste's target, replace the fresh span

    def test_undo_stops_when_the_check_fails(self):
        platform = FakePlatform(Context("something else", 10, 20, True, False))
        self.assertFalse(edit_logic.undo(platform, CTX, "old", "new"))
        self.assertEqual(platform.log, [("select_back", 3), ("capture",), ("collapse",)])

    def test_undo_requires_the_range_the_paste_landed_in(self):
        ctx = Context("old", 10, 20, True, False, caret=(5, 3))
        platform = FakePlatform(Context("new", 10, 20, True, False, caret=(5, 3)))
        self.assertTrue(edit_logic.undo(platform, ctx, "old", "new"))
        platform = FakePlatform(Context("new", 10, 20, True, False, caret=(30, 3)))  # the same text elsewhere
        self.assertFalse(edit_logic.undo(platform, ctx, "old", "new"))
        self.assertEqual(platform.log, [("select_back", 3), ("capture",), ("collapse",)])

    def test_a_platform_without_collapse_leaves_the_selection(self):
        bare = type("Bare", (), {k: v for k, v in vars(FakePlatform).items() if k != "collapse"})(
            Context("something else", 10, 20, True, False))
        self.assertFalse(edit_logic.undo(bare, CTX, "old", "new"))
        self.assertEqual(bare.log, [("select_back", 3), ("capture",)])


if __name__ == "__main__":
    unittest.main()
