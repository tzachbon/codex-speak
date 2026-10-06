import array
import math
import os
import tempfile
import threading
import unittest

from pynput.mouse import Button

from select_to_tts import clipboard, lang, settings
from select_to_tts.audio import NoAudioError, PcmPlayer, Stretcher
from select_to_tts.codex_rt import CodexEngine
from select_to_tts.engines import Chain, EdgeEngine, sapi_rate
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

    def speak(self, text, tag, on_done, on_audio):
        self.calls += 1
        if not self.err:
            on_audio()
        on_done(self.err)

    def stop(self):
        pass

    def pause(self):
        self.calls += 100

    def resume(self):
        self.calls += 1000


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

    def test_audio_start_is_reported_once_and_not_after_stop(self):
        heard = []
        chain = Chain([Fake("Edge")])
        chain.speak("hi", None, lambda err: None, lambda: heard.append(1))
        self.assertEqual(heard, [1])
        late = Fake("Codex")
        late.speak = lambda text, tag, on_done, on_audio: setattr(late, "start", on_audio)
        chain = Chain([late])
        chain.speak("hi", None, lambda err: None, lambda: heard.append(2))
        chain.stop()
        late.start()  # audio that arrives after Stop is ignored
        self.assertEqual(heard, [1])

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

    def test_pause_and_resume_reach_the_engine_that_spoke(self):
        a, b = Fake("Codex", NoAudioError("x")), Fake("Edge")
        chain, _ = self.run_chain(a, b)
        chain.pause()
        chain.resume()
        self.assertEqual((a.calls, b.calls), (1, 1101))

    def test_pause_before_a_fallback_carries_over(self):
        a, b = Fake("Codex", NoAudioError("x")), Fake("Edge")
        a.speak = lambda text, tag, on_done, on_audio: setattr(a, "fail", lambda: on_done(NoAudioError("x")))
        chain = Chain([a, b])
        chain.speak("hi", None, lambda err: None)
        chain.pause()  # while Codex is still connecting
        a.fail()  # Codex gives up, Edge takes over
        self.assertEqual(b.calls, 1 + 100)  # Edge spoke, then was paused

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


class Player(unittest.TestCase):
    def test_paused_player_plays_silence_and_keeps_the_queue(self):
        paused = threading.Event()
        p = PcmPlayer.__new__(PcmPlayer)  # no sound device: drive the callback directly
        p._buf, p._lock, p._width, p._paused = bytearray(b"\x01\x02" * 8), threading.Lock(), 2, paused
        out = bytearray(8)
        paused.set()
        p._fill(out, 4, None, None)
        self.assertEqual((bytes(out), len(p._buf)), (bytes(8), 16))
        paused.clear()
        p._fill(out, 4, None, None)
        self.assertEqual((bytes(out), len(p._buf)), (b"\x01\x02" * 4, 8))


class StopClearsPause(unittest.TestCase):
    def test_a_stopped_paused_engine_starts_unpaused(self):
        for engine in (CodexEngine(), EdgeEngine()):
            engine.pause()
            engine.stop()
            self.assertFalse(engine.paused.is_set(), engine.name)
            engine.close()


class Settings(unittest.TestCase):
    def test_load_defaults_clamps_and_survives_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "settings.json")
            self.assertEqual(settings.load(path), settings.DEFAULTS)
            settings.save({"engine": "Edge", "speed": 9, "clipboard_fallback": False}, path)
            self.assertEqual(settings.load(path), {**settings.DEFAULTS, "engine": "Edge", "speed": 2.0,
                                                   "clipboard_fallback": False})
            for junk in ("{not json", "[1, 2]", "null", '{"engine": "Bogus", "speed": "fast"}',
                         '{"speed": NaN, "clipboard_fallback": "false"}', '{"speed": true, "engine": 3}', '{"speed": 1' + '0' * 400 + '}'):
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


class SttServerRestart(unittest.TestCase):
    def test_restarted_server_keeps_its_url(self):
        from pathlib import Path
        from select_to_tts import stt_server
        with tempfile.TemporaryDirectory() as d:
            conn = Path(d) / "stt-connection.json"
            urls = []
            for _ in range(2):
                server = stt_server.start(port=0, connection_file=conn)
                urls.append(server.base_url.split("/")[3])
                server.shutdown()
                server.server_close()
            self.assertEqual(urls[0], urls[1])
            conn.write_text('{"base_url": "http://127.0.0.1:1/short/v1"}', encoding="utf-8")
            self.assertIsNone(stt_server.saved_token(conn))


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
