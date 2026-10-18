"""The ordered voice sources: the saved list, the chain order, and how core applies them."""
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from harness_discussion import codex_rt, settings
from harness_discussion.audio import NoAudioError
from harness_discussion.engines import Chain

from test_core import CoreTest, Engine

ALL = settings.DEFAULT_SOURCES


class Load(unittest.TestCase):
    def load(self, saved):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with open(path, "w") as f:
                json.dump(saved, f)
            return settings.load(path)

    def test_defaults_put_cursor_first_and_drop_the_engine_key(self):
        self.assertEqual(ALL[:2], ["Cursor", "Codex"])
        self.assertEqual(settings.DEFAULTS["sources"], [[n, True] for n in ALL])
        self.assertEqual(settings.DEFAULTS["voices"], {})
        self.assertNotIn("engine", settings.DEFAULTS)

    def test_a_legacy_engine_goes_first_and_the_rest_are_disabled(self):
        s = self.load({"engine": "Codex"})
        self.assertEqual(s["sources"], [["Codex", True]] + [[n, False] for n in ALL if n != "Codex"])
        self.assertNotIn("engine", s)

    def test_a_legacy_auto_keeps_the_default_order(self):
        self.assertEqual(self.load({"engine": None})["sources"], [[n, True] for n in ALL])
        self.assertEqual(self.load({"engine": "Bogus"})["sources"], [[n, True] for n in ALL])

    def test_unknown_and_duplicate_names_are_dropped_and_missing_ones_appended(self):
        s = self.load({"sources": [["Codex", False], ["Bogus", True], ["Codex", True], "junk",
                                   [["Cursor"], True], ["Cursor", "yes"]]})
        self.assertEqual(s["sources"], [["Codex", False]] + [[n, True] for n in ALL if n != "Codex"])
        for junk in (None, "Codex", {"Codex": True}):
            self.assertEqual(self.load({"sources": junk})["sources"], [[n, True] for n in ALL])

    def test_saved_sources_ignore_a_legacy_engine(self):
        saved = [[n, i == 0] for i, n in enumerate(reversed(ALL))]
        self.assertEqual(self.load({"sources": saved, "engine": "Codex"})["sources"], saved)

    def test_voices_keep_only_text(self):
        self.assertEqual(self.load({"voices": {"Cursor": "eve", "Codex": 3}})["voices"], {"Cursor": "eve"})
        self.assertEqual(self.load({"voices": ["eve"]})["voices"], {})


class Fake:
    speed = 1.0

    def __init__(self, name, err=None, max_speed=None):
        self.name, self.err, self.calls = name, err, 0
        if max_speed:
            self.max_speed = max_speed

    def speak(self, text, tag, on_done, on_audio):
        self.calls += 1
        on_done(self.err)

    def stop(self):
        pass


class Order(unittest.TestCase):
    def names(self, chain):
        return [e.name for e in chain.order()]

    def test_order_follows_enabled_and_skips_disabled(self):
        chain = Chain([Fake("Cursor"), Fake("Codex"), Fake("Edge")])
        self.assertEqual(self.names(chain), ["Cursor", "Codex", "Edge"])
        chain.enabled = ["Edge", "Cursor"]
        self.assertEqual(self.names(chain), ["Edge", "Cursor"])
        chain.only = "Codex"  # a pin or a Test button still wins
        self.assertEqual(self.names(chain), ["Codex"])

    def test_the_speed_window_skips_codex_and_keeps_cursor(self):
        engines = [Fake("Cursor", max_speed=2.0), Fake("Codex", max_speed=1.0), Fake("Slow")]
        engines[2].min_speed = 1.75
        for e in engines:
            e.speed = 1.5
        chain = Chain(engines)
        self.assertEqual(self.names(chain), ["Cursor"])
        chain.enabled = ["Codex"]  # nothing enabled fits: the enabled ones still read
        self.assertEqual(self.names(chain), ["Codex"])

    def test_with_every_source_disabled_the_read_uses_all(self):
        chain = Chain([Fake("Cursor"), Fake("Codex")])
        chain.enabled = []
        self.assertEqual(self.names(chain), ["Cursor", "Codex"])

    def test_on_engine_fires_once_per_attempt_with_the_name(self):
        chain, started = Chain([Fake("Cursor", NoAudioError("x")), Fake("Codex")]), []
        chain.on_engine = started.append
        chain.speak("hi", None, lambda err: None)
        self.assertEqual(started, ["Cursor", "Codex"])


class CodexStatus(unittest.TestCase):
    def test_missing_only_without_the_cli(self):
        engine = codex_rt.CodexEngine()
        self.addCleanup(engine.close)
        with patch.object(codex_rt, "codex_exe", side_effect=FileNotFoundError):
            self.assertEqual(engine.status(), "missing")
        with patch.object(codex_rt, "codex_exe", return_value="/bin/codex"):
            self.assertEqual(engine.status(), "ready")


class Voiced(Engine):
    voices, voice = (("ara", "Ara"), ("eve", "Eve")), None


class CoreSources(unittest.TestCase):
    make = CoreTest.make

    def test_sources_set_the_order_and_clear_a_pin(self):
        app = self.make(Engine("Cursor"), Engine("Codex"))
        app.chain.only = "Cursor"
        app.change("sources", [["Codex", True], ["Cursor", False]])
        self.assertEqual((app.chain.enabled, app.chain.only), (["Codex"], None))

    def test_sources_wait_for_the_selection_to_end(self):
        cursor, codex = Engine("Cursor"), Engine("Codex")
        app = self.make(cursor, codex)
        app.change("sources", [["Cursor", True], ["Codex", True]])
        app.play("One. Two.", None)
        app.change("sources", [["Codex", True], ["Cursor", True]])
        self.assertEqual(app.chain.enabled, ["Cursor", "Codex"])  # captured for the whole selection
        app.stop()
        self.assertEqual(app.chain.enabled, ["Codex", "Cursor"])

    def test_change_mirrors_sources_to_an_open_settings_window(self):
        app = self.make(Engine("Cursor"))
        seen = []
        app.settings_win = type("Win", (), {"alive": True, "set_sources": lambda self, v: seen.append(v)})()
        app.change("sources", [["Cursor", True]])
        self.assertEqual(seen, [[["Cursor", True]]])

    def test_voices_are_checked_against_the_engine(self):
        cursor, local = Voiced("Cursor"), Engine("macOS")
        app = self.make(cursor, local)
        app.change("voices", {"Cursor": "eve", "macOS": "x"})
        self.assertEqual(cursor.voice, "eve")
        self.assertFalse(hasattr(local, "voice"))
        app.change("voices", {"Cursor": "bogus"})
        self.assertIsNone(cursor.voice)

    def test_play_only_reads_through_that_source_then_unpins(self):
        cursor, codex = Engine("Cursor"), Engine("Codex")
        app = self.make(cursor, codex)
        app.play("This is Codex.", None, only="Codex")
        self.assertEqual((cursor.spoken, codex.spoken), ([], ["This is Codex."]))
        codex.done[0](None)
        app.pump()
        self.assertIsNone(app.chain.only)

    def test_engine_events_and_the_status_cache(self):
        cursor = Engine("Cursor", fail=True)
        cursor.status = lambda: "signed_out"
        app = self.make(cursor, Engine("Codex"))
        refreshed = []
        app.settings_win = type("Win", (), {"alive": True, "refresh_sources": lambda self: refreshed.append(1)})()
        self.assertEqual(app.statuses, {})
        app.play("Hello.", None)
        self.assertEqual([app.events.get_nowait() for _ in range(2)], [("engine", "Cursor"), ("engine", "Codex")])
        app.refresh_statuses()
        for _ in range(200):
            if not app.events.empty():
                break
            threading.Event().wait(0.01)
        app.pump()
        self.assertEqual(app.statuses, {"Cursor": "signed_out", "Codex": "ready"})
        self.assertEqual(refreshed, [1])


del CoreTest  # imported for its helpers; its tests run in test_core


if __name__ == "__main__":
    unittest.main()
