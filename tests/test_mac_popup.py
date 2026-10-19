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

    def _playing_bar(self):
        import AppKit
        from harness_discussion.mac import popup
        AppKit.NSApplication.sharedApplication()
        noop = lambda *a: None
        bar = popup.Popup(1.0, on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop,
                          on_speed=noop, on_settings=noop, on_source=noop, sources=lambda: [])
        self.addCleanup(bar.hide)
        bar.show("x", 400, 400)
        bar.set_playing(True)
        return bar

    def test_a_long_caption_is_one_line_and_a_font_change_resizes_it(self):
        bar = self._playing_bar()
        bar.set_caption("Hi.")
        one_line = bar.caption.win.frame().size.height
        self.assertIsNone(bar.caption._timer)  # short text is centered and still
        bar.set_caption("word " * 400)
        self.assertEqual(bar.caption.win.frame().size.height, one_line)
        self.assertEqual(bar.caption.win.frame().size.width, 340)
        bar.set_caption("Hi.")
        bar.configure_captions(20, False, 0.6)
        self.assertGreater(bar.caption.win.frame().size.height, one_line)

    def test_a_long_caption_scrolls_to_its_end_pauses_and_keeps_its_place_as_it_grows(self):
        bar = self._playing_bar()
        c = bar.caption
        with mock.patch("harness_discussion.mac.caption.time.monotonic", side_effect=[0.0, 1.0]):
            bar.set_caption("word " * 40)
            self.assertIsNotNone(c._timer)
            start_x = c.field.frame().origin.x
            c._tick()
        self.assertAlmostEqual(c.offset, 18)
        self.assertAlmostEqual(c.field.frame().origin.x, start_x - 18)
        bar.set_caption_paused(True)
        self.assertIsNone(c._timer)
        bar.set_caption("word " * 41)
        self.assertAlmostEqual(c.offset, 18)  # growing text keeps its place
        self.assertIsNone(c._timer)  # and stays paused
        bar.set_caption_paused(False)
        self.assertIsNotNone(c._timer)
        with mock.patch("harness_discussion.mac.caption.time.monotonic", return_value=1e6):
            c._tick()
        self.assertEqual(c.offset, c._end())
        self.assertIsNone(c._timer)  # stops at the end
        bar.set_caption("Another sentence " * 20)
        self.assertEqual(c.offset, 0)

    def test_a_read_stopped_while_paused_does_not_freeze_the_next_caption(self):
        bar = self._playing_bar()
        bar.set_caption_paused(True)
        bar.set_playing(False)
        bar.set_playing(True)
        bar.set_caption("word " * 40)
        self.assertIsNotNone(bar.caption._timer)

    def test_a_right_to_left_caption_starts_at_its_end_and_scrolls_back(self):
        bar = self._playing_bar()
        c = bar.caption
        with mock.patch("harness_discussion.mac.caption.time.monotonic", side_effect=[0.0, 1.0]):
            bar.set_caption("שלום עולם " * 40)
            self.assertEqual(c.offset, c._end())
            c._tick()
        self.assertAlmostEqual(c.offset, c._end() - 18)

    def test_a_growing_right_to_left_caption_keeps_its_right_edge_and_scrolls(self):
        bar = self._playing_bar()
        c = bar.caption
        bar.set_caption("שלום")
        self.assertEqual(c.offset, 0)  # fits, so it does not scroll
        bar.set_caption("שלום " + "עולם " * 40)
        self.assertEqual(c.offset, c._end())  # still showing its start, on the right
        self.assertIsNotNone(c._timer)


if __name__ == "__main__":
    unittest.main()


def host_module():
    from harness_discussion.mac import host
    return host


class MenuBarMenuTest(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace
        from harness_discussion.mac import host
        self.host = host.MacHost()
        self.addCleanup(lambda: __import__("AppKit").NSStatusBar.systemStatusBar().removeStatusItem_(self.host.item))
        self.changes, self.picks = [], []
        source = SimpleNamespace(name="Codex")
        self.popup = SimpleNamespace(playing=False, paused=False, toggles=0)
        self.popup._toggle = lambda: setattr(self.popup, "toggles", self.popup.toggles + 1)
        self.host.app = SimpleNamespace(
            popup=self.popup, cfg={"speed": 1.25}, chain=SimpleNamespace(active_name=None, last=None, order=lambda: [source]),
            _source_choices=lambda: [("Codex", None), ("macOS", None), ("Cursor", "Sign in…")],
            change=lambda key, value: self.changes.append((key, value)), _popup_source=self.picks.append)

    def titles(self, menu):
        return [i.title() for i in menu.itemArray() if not i.isHidden() and not i.isSeparatorItem()]

    def pick(self, menu, title):
        item = next(i for i in menu.itemArray() if i.title() == title)
        item.target().run_(item)

    def test_idle_menu_lists_controls_and_hides_playback(self):
        self.host.refresh_menu()
        titles = self.titles(self.host.menu)
        self.assertEqual(titles[0], "Ready: select text to read")
        self.assertNotIn("Pause", titles)
        self.assertNotIn("Stop", titles)
        for title in ("Speed", "Voice Source", "Show Popup on Selection", "Settings…", "Quit Harness Discussion"):
            self.assertIn(title, titles)
        speed = self.host.speed_menu
        self.assertEqual([i.title() for i in speed.itemArray() if i.state()], ["1.25×"])
        sources = self.host.source_menu
        self.assertEqual(self.titles(sources), ["Codex", "macOS", "Cursor: Sign in…"])
        self.assertEqual([i.title() for i in sources.itemArray() if i.state()], ["Codex"])

    def test_picks_reach_the_app(self):
        self.host.refresh_menu()
        self.pick(self.host.speed_menu, "1.5×")
        self.pick(self.host.source_menu, "Cursor: Sign in…")
        self.assertEqual((self.changes, self.picks), ([("speed", 1.5)], ["Cursor"]))

    def test_toggle_stops_and_restarts_the_selection_trigger(self):
        with mock.patch.object(host_module(), "SelectionTrigger") as trigger:
            self.host.start_trigger("on_selection", "on_press")
            self.host.refresh_menu()
            self.assertEqual(self.host.listen_item.state(), 1)
            self.pick(self.host.menu, "Show Popup on Selection")
            self.host.refresh_menu()
            self.assertEqual((self.host.trigger, self.host.listen_item.state()), (None, 0))
            trigger.return_value.stop.assert_called_once()
            self.pick(self.host.menu, "Show Popup on Selection")
            self.assertEqual(trigger.call_args_list, [mock.call("on_selection", "on_press")] * 2)

    def test_reading_shows_pause_then_resume(self):
        self.popup.playing = True
        self.host.app.chain.last, self.host.app.chain.active_name = "Cursor", "Codex"  # Cursor failed over
        self.host.refresh_menu()
        self.assertEqual(self.titles(self.host.menu)[:3], ["Reading with Codex", "Pause", "Stop"])
        self.pick(self.host.menu, "Pause")
        self.assertEqual(self.popup.toggles, 1)
        self.popup.paused = True
        self.host.refresh_menu()
        self.assertEqual(self.titles(self.host.menu)[:3], ["Paused", "Resume", "Stop"])
