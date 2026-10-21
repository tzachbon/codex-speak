"""The Mac edit guards with capture and paste patched: no app is driven."""
import sys
import unittest
from unittest import mock

if sys.platform != "darwin":
    raise unittest.SkipTest("macOS only")

from Foundation import NSString

from harness_discussion.edit_logic import Context
from harness_discussion.mac import edit

FIELD, OTHER = NSString.stringWithString_("field"), NSString.stringWithString_("other")
CTX = Context("", 1, 2, True, False, FIELD, (5, 0))


class GuardTest(unittest.TestCase):
    def typed(self, now):
        pasted = []
        with mock.patch.object(edit, "capture", return_value=now), \
                mock.patch.object(edit, "_paste", side_effect=lambda t: pasted.append(t) or True):
            ok = edit.type_at_caret("hello", CTX)
        return ok, pasted

    def test_dictation_types_only_at_the_captured_caret_in_the_captured_field(self):
        self.assertEqual(self.typed(Context("", 1, 2, True, False, FIELD, (5, 0))), (True, ["hello"]))
        self.assertEqual(self.typed(Context("", 1, 2, True, False, OTHER, (5, 0))), (False, []))
        self.assertEqual(self.typed(Context("x", 1, 2, True, False, FIELD, (0, 3))), (False, []))  # moved selection
        self.assertEqual(self.typed(Context("", 1, 2, True, True, FIELD, (5, 0))), (False, []))  # now secure
        self.assertEqual(self.typed(None), (False, []))

    def test_select_back_accepts_the_moved_caret_after_a_paste(self):
        with mock.patch.object(edit, "capture", return_value=Context("", 1, 2, True, False, FIELD, (9, 0))), \
                mock.patch.object(edit, "_focused", return_value=None), mock.patch.object(edit, "_key"):
            self.assertTrue(edit.select_back(4, CTX))
        with mock.patch.object(edit, "capture", return_value=Context("", 1, 2, True, False, OTHER, (9, 0))):
            self.assertFalse(edit.select_back(4, CTX))


if __name__ == "__main__":
    unittest.main()
