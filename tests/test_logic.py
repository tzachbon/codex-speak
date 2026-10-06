import array
import math
import os
import tempfile
import unittest

from pynput.mouse import Button

from select_to_tts import clipboard, lang, settings
from select_to_tts.audio import NoAudioError, Stretcher
from select_to_tts.engines import Chain, sapi_rate
from select_to_tts.trigger import SelectionTrigger


class Lang(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(lang.detect("שלום עולם"), "he-IL")
        self.assertEqual(lang.detect("hello world"), "en-US")
        self.assertEqual(lang.detect("שלום hello עולם"), "he-IL")
        self.assertEqual(lang.detect("Привет мир"), "ru-RU")
        self.assertEqual(lang.detect("مرحبا بالعالم"), "ar-SA")
        self.assertEqual(lang.detect("123"), "en-US")


class Clipboard(unittest.TestCase):
    def test_safe_to_borrow(self):
        self.assertTrue(clipboard.safe_to_borrow(set()))
        self.assertTrue(clipboard.safe_to_borrow({13, 1, 7, 16, 49353}))  # text + HTML Format
        self.assertTrue(clipboard.safe_to_borrow({2, 8, 17}))  # bitmap backed by a DIB
        self.assertFalse(clipboard.safe_to_borrow({2}))  # bare HBITMAP
        self.assertFalse(clipboard.safe_to_borrow({14, 13}))  # enhanced metafile


class Fake:
    speed = 1.0

    def __init__(self, name, err=None):
        self.name, self.err, self.calls = name, err, 0

    def speak(self, text, tag, on_done):
        self.calls += 1
        on_done(self.err)

    def stop(self):
        pass


class ChainTest(unittest.TestCase):
    def run_chain(self, *engines, only=None):
        chain, result = Chain(list(engines)), []
        chain.only = only
        chain.speak("hi", None, result.append)
        return chain, result

    def test_falls_back_only_before_audio(self):
        a, b = Fake("Codex", NoAudioError("x")), Fake("Edge")
        chain, result = self.run_chain(a, b)
        self.assertEqual((result, chain.last, b.calls), ([None], "Edge", 1))

    def test_mid_playback_failure_is_reported_not_retried(self):
        a, b = Fake("Codex", RuntimeError("cut")), Fake("Edge")
        chain, result = self.run_chain(a, b)
        self.assertEqual((type(result[0]), b.calls), (RuntimeError, 0))

    def test_auto_skips_engines_slower_than_the_speed(self):
        codex, edge = Fake("Codex"), Fake("Edge")
        codex.max_speed = 1.0
        for e in (codex, edge):
            e.speed = 1.5
        chain, result = self.run_chain(codex, edge)
        self.assertEqual((codex.calls, edge.calls, chain.last), (0, 1, "Edge"))
        chain, result = self.run_chain(codex, edge, only="Codex")  # explicit choice still wins
        self.assertEqual(codex.calls, 1)

    def test_only_never_touches_other_engines(self):
        a, b = Fake("Codex"), Fake("Windows", NoAudioError("x"))
        chain, result = self.run_chain(a, b, only="Windows")
        self.assertEqual((a.calls, type(result[0])), (0, NoAudioError))


class Trigger(unittest.TestCase):
    def test_drag_and_double_click(self):
        hits = []
        t = SelectionTrigger(lambda x, y: hits.append((x, y)), lambda x, y: None)
        click = lambda x, y: (t._click(x, y, Button.left, True), t._click(x, y, Button.left, False))
        t._click(0, 0, Button.left, True)
        t._click(100, 0, Button.left, False)  # drag
        click(500, 500)  # single click: nothing
        click(500, 500)  # second click: double-click
        t._click(0, 0, Button.right, True)  # other buttons ignored
        self.assertEqual(hits, [(100, 0), (500, 500)])


class Settings(unittest.TestCase):
    def test_load_defaults_clamps_and_survives_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "settings.json")
            self.assertEqual(settings.load(path), settings.DEFAULTS)
            settings.save({"engine": "Edge", "speed": 9, "clipboard_fallback": False}, path)
            self.assertEqual(settings.load(path), {"engine": "Edge", "speed": 2.0, "clipboard_fallback": False})
            for junk in ("{not json", "[1, 2]", "null", '{"engine": "Bogus", "speed": "fast"}',
                         '{"speed": NaN, "clipboard_fallback": "false"}', '{"speed": true, "engine": 3}'):
                with open(path, "w") as f:
                    f.write(junk)
                self.assertEqual(settings.load(path), settings.DEFAULTS)

    def test_startup_round_trip(self):
        name = "select-to-tts-unittest"
        try:
            settings.set_startup(True, name)
            self.assertTrue(settings.startup_enabled(name))
            settings.set_startup(False, name)
            self.assertFalse(settings.startup_enabled(name))
            settings.set_startup(False, name)  # already off: no error
        finally:
            settings.set_startup(False, name)


class Speed(unittest.TestCase):
    def test_stretcher_keeps_pitch_changes_length(self):
        tone = array.array("h", (int(8000 * math.sin(2 * math.pi * 440 * i / 24000))
                                 for i in range(24000))).tobytes()
        for speed, expected in ((1.0, 24000), (1.5, 16000), (0.75, 32000), (0.5, 48000)):
            st = Stretcher(speed)
            out = b"".join(st(tone[i:i + 960]) for i in range(0, len(tone), 960))
            self.assertAlmostEqual(len(out) / 2, expected, delta=expected * 0.06)

    def test_sapi_rate(self):
        self.assertEqual([sapi_rate(s) for s in (0.5, 1.0, 1.5, 2.0, 3.0)], [-6, 0, 4, 6, 10])


if __name__ == "__main__":
    unittest.main()
