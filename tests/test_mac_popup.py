import sys
import unittest
from unittest import mock

if sys.platform != "darwin":
    raise unittest.SkipTest("macOS only")


class PopupSourceTest(unittest.TestCase):
    def test_label_follows_set_source_and_a_pick_reaches_on_source(self):
        import AppKit
        from harness_discussion.mac import popup
        AppKit.NSApplication.sharedApplication()
        picked = []
        noop = lambda *a: None
        bar = popup.Popup(1.0, on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop,
                          on_speed=noop, on_settings=noop, on_source=picked.append, sources=lambda: [("Codex", None), ("macOS", None), ("Cursor", "Sign in…")])
        bar.set_source("Codex")
        self.assertEqual(bar.source_btn.title(), "Codex ▾")
        menus = []
        with mock.patch.object(bar, "_popup", lambda button, choices, current, pick: menus.append(
                (choices, current)) or pick("macOS")):
            bar.source_btn.performClick_(None)
        choices, current = menus[0]
        self.assertEqual(([c and c[:2] for c in choices], current, picked),
                         ([("Codex", "Codex"), ("macOS", "macOS"), None, ("Cursor", "Cursor: Sign in…")], "Codex", ["macOS"]))

    def test_the_bar_keeps_its_width_through_picks_and_playback(self):
        import AppKit
        from harness_discussion.mac import popup
        AppKit.NSApplication.sharedApplication()
        noop = lambda *a: None
        bar = popup.Popup(1.0, on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop,
                          on_speed=noop, on_settings=noop, on_source=noop, sources=lambda: [])
        bar.set_source("macOS")
        self.assertEqual((bar.speed_btn.title(), bar.lang_btn.title()), ("1× ▾", "Auto ▾"))
        width = lambda: bar.win.contentView().fittingSize().width
        before = width()
        bar.set_source("Codex")
        bar.set_speed(1.75)
        bar.set_playing(True)
        self.assertEqual(width(), before)

    def test_the_caption_shows_the_sentence_above_the_bar_while_playing(self):
        import AppKit
        from harness_discussion.mac import popup
        AppKit.NSApplication.sharedApplication()
        noop = lambda *a: None
        bar = popup.Popup(1.0, on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop,
                          on_speed=noop, on_settings=noop, on_source=noop, sources=lambda: [])
        bar.show("Hello there.", 400, 400)
        bar.set_caption("Not playing yet.")
        self.assertFalse(bar.caption.win.isVisible())
        bar.set_playing(True)
        bar.set_caption("Hello   there.")
        self.assertTrue(bar.caption.win.isVisible())
        self.assertEqual(bar.caption.field.stringValue(), "Hello there.")
        self.assertGreater(bar.caption.win.frame().origin.y, bar.win.frame().origin.y)
        bar.set_playing(False)
        self.assertFalse(bar.caption.win.isVisible())
        bar.hide()

    def test_a_long_caption_stays_three_lines_and_a_font_change_resizes_it(self):
        import AppKit
        from harness_discussion.mac import popup
        AppKit.NSApplication.sharedApplication()
        noop = lambda *a: None
        bar = popup.Popup(1.0, on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop,
                          on_speed=noop, on_settings=noop, on_source=noop, sources=lambda: [])
        self.addCleanup(bar.hide)
        bar.show("x", 400, 400)
        bar.set_playing(True)
        bar.set_caption("Hi.")
        one_line = bar.caption.win.frame().size.height
        bar.set_caption("word " * 400)
        self.assertLess(bar.caption.win.frame().size.height, one_line * 3.5)
        bar.set_caption("Hi.")
        bar.configure_captions(20, False, 0.6)
        self.assertGreater(bar.caption.win.frame().size.height, one_line)


if __name__ == "__main__":
    unittest.main()
