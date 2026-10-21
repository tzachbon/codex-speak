import sys
import unittest
from unittest import mock

if sys.platform != "darwin":
    raise unittest.SkipTest("macOS only")


def _bar(**kw):
    import AppKit
    from harness_discussion.mac import popup
    AppKit.NSApplication.sharedApplication()
    noop = lambda *a: None
    args = dict(on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop, on_speed=noop,
                on_settings=noop, on_source=noop, sources=lambda: [], on_skip=noop)
    return popup.Popup(1.0, **{**args, **kw})


def _shown(bar):
    return [v for v in bar.row.arrangedSubviews() if not v.isHidden()]


def _walk(entries, path):
    """The entry at a path of titles through the "…" menu entries."""
    for title in path:
        entries = next(e for e in entries if e and e[0] == title)
        if title != path[-1]:
            entries = entries[1]
    return entries


class PopupSourceTest(unittest.TestCase):
    def test_the_more_menu_routes_voice_language_speed_and_settings(self):
        calls = []
        bar = _bar(on_source=lambda n: calls.append(("source", n)), on_lang=lambda t: calls.append(("lang", t)),
                   on_speed=lambda s: calls.append(("speed", s)), on_settings=lambda: calls.append(("settings",)),
                   on_summarize=lambda text, tag: calls.append(("summarize", text)),
                   sources=lambda: [("Codex", None), ("macOS", None), ("Cursor", "Sign in…")])
        bar.set_source("Codex")
        entries = bar.menu_entries()
        self.assertEqual([e and e[0] for e in entries], ["Voice", "Language", "Speed", None, "Summarize", None, "Settings…"])
        voices = _walk(entries, ["Voice"])[1]
        self.assertEqual([v and (v[0], v[2]) for v in voices],
                         [("Codex", True), ("macOS", False), None, ("Cursor: Sign in…", False)])
        _walk(entries, ["Voice", "macOS"])[1]()
        _walk(entries, ["Language", "Hebrew"])[1]()
        _walk(entries, ["Speed", "1.5×"])[1]()
        _walk(entries, ["Summarize"])[1]()
        _walk(entries, ["Settings…"])[1]()
        self.assertEqual(calls, [("source", "macOS"), ("lang", "he-IL"), ("speed", 1.5), ("summarize", ""),
                                 ("settings",)])

    def test_rewrite_appears_only_with_in_place_editing(self):
        picked = []
        bar = _bar(on_rewrite=lambda text, mode: picked.append((text, mode)), modes=lambda: ["Fix errors", "Email"])
        bar.text = "hi"
        self.assertNotIn("Rewrite", [e and e[0] for e in bar.menu_entries()])  # a selection that can't be edited
        bar.set_editable(True)
        rewrite = _walk(bar.menu_entries(), ["Rewrite"])[1]
        self.assertEqual([m[0] for m in rewrite], ["Fix errors", "Email"])
        rewrite[1][1]()
        self.assertEqual(picked, [("hi", "Email")])
        self.assertNotIn("Rewrite", [e and e[0] for e in _bar().menu_entries()])

    def test_layouts_for_writing_reading_and_playing(self):
        bar = _bar(on_rewrite=lambda text, mode: None, modes=lambda: ["Fix errors"])
        self.addCleanup(bar.hide)
        bar.show("Some text.", 400, 400, editable=True)
        chips = [bar.source_btn, bar.speed_btn, bar.more_btn, bar.close_btn]
        self.assertEqual(_shown(bar), [bar.rewrite_btn, bar.mode_btn, bar.divider, bar.btn, bar.ai_btn, *chips])
        left = bar.win.frame().origin.x
        bar.set_editable(False)
        self.assertEqual(_shown(bar), [bar.btn, bar.ai_btn, *chips])
        self.assertEqual(bar.win.frame().origin.x, left)  # the left edge stays anchored
        self.assertEqual(bar.effect.layer().cornerRadius(), bar.win.frame().size.height / 2)
        bar.set_playing(True)
        self.assertEqual(_shown(bar), [bar.btn, bar.back_btn, bar.next_btn, bar.stop_btn, *chips])
        bar.set_playing(False)
        bar.set_summarize_progress(0.4)
        self.assertEqual(_shown(bar), [bar.btn, bar.ai_progress, *chips])
        self.assertEqual(bar.ai_progress.doubleValue(), 0.4)
        no_writer = _bar()
        self.addCleanup(no_writer.hide)
        no_writer.show("Some text.", 400, 400, editable=True)
        self.assertEqual(_shown(no_writer), [no_writer.btn, no_writer.ai_btn, no_writer.source_btn,
                                             no_writer.speed_btn, no_writer.more_btn, no_writer.close_btn])

    def test_the_voice_and_speed_chips_pick_and_show_the_choice(self):
        picks = []
        bar = _bar(on_source=lambda n: picks.append(n), on_speed=lambda s: picks.append(s),
                   sources=lambda: [("Codex", None), ("macOS", None)])
        bar.set_source("Codex")
        self.assertIn("Codex", str(bar.source_btn.attributedTitle().string()))
        self.assertEqual([v[0] for v in bar._voice_entries()], ["Codex", "macOS"])
        bar._voice_entries()[1][1]()
        next(e for e in bar._speed_entries() if e[0] == "1.5×")[1]()
        self.assertEqual(picks, ["macOS", 1.5])
        self.assertIn("1.5×", str(bar.speed_btn.attributedTitle().string()))

    def test_the_rewrite_button_uses_the_last_mode_and_stays_while_rewriting(self):
        picked = []
        bar = _bar(on_rewrite=lambda text, mode: picked.append(mode), modes=lambda: ["Fix errors"])
        self.addCleanup(bar.hide)
        bar.show("x", 400, 400, editable=True)
        bar.set_last_mode("Email")
        self.assertIn("Email", str(bar.rewrite_btn.attributedTitle().string()))
        bar.rewrite_btn.performClick_(None)
        bar.set_rewriting(True)
        self.assertIsNone(bar._hide_timer)
        bar.rewrite_btn.performClick_(None)  # disabled while rewriting
        self.assertEqual(picked, ["Email"])

    def test_summarize_sends_the_selection(self):
        import AppKit
        from harness_discussion.mac import popup
        AppKit.NSApplication.sharedApplication()
        noop, asked = (lambda *a: None), []
        bar = popup.Popup(1.0, on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop,
                          on_speed=noop, on_settings=noop, on_source=noop, sources=lambda: [],
                          on_summarize=lambda text, tag: asked.append((text, tag)), on_skip=noop)
        self.addCleanup(bar.hide)
        bar.show("Some text.", 400, 400)
        bar.ai_btn.performClick_(None)
        self.assertEqual(asked, [("Some text.", None)])
        self.assertIsNotNone(bar._hide_timer)  # nothing started, so the bar still hides on its own
        import Quartz
        alpha = lambda: Quartz.CGColorGetAlpha(bar.ai_btn.layer().backgroundColor())
        bar.set_summary()
        self.assertGreater(alpha(), 0)  # marked while the summary reads
        bar.set_playing(False)
        self.assertEqual(alpha(), 0)

    def test_the_caption_shows_the_sentence_above_the_bar_while_playing(self):
        import AppKit
        from harness_discussion.mac import popup
        AppKit.NSApplication.sharedApplication()
        noop = lambda *a: None
        bar = popup.Popup(1.0, on_play=noop, on_stop=noop, on_pause=noop, on_resume=noop, on_lang=noop,
                          on_speed=noop, on_settings=noop, on_source=noop, sources=lambda: [], on_skip=noop)
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
                          on_speed=noop, on_settings=noop, on_source=noop, sources=lambda: [], on_skip=noop)
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
