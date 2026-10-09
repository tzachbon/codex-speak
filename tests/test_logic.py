import array
import math
import os
import tempfile
import threading
import unittest

from pynput.mouse import Button

from codex_speak import clipboard, lang, settings
from codex_speak.audio import NoAudioError, PcmPlayer, Stretcher
from codex_speak.codex_rt import CodexEngine
from codex_speak.engines import Chain, EdgeEngine, sapi_rate
from codex_speak.trigger import SelectionTrigger


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
        self.tags = []

    def speak(self, text, tag, on_done, on_audio):
        self.calls += 1
        self.tags.append(tag)
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
    def test_new_speech_stays_busy_when_old_completion_passed_its_generation_guard(self):
        callbacks, guarded, resume = [], threading.Event(), threading.Event()
        main_thread = threading.get_ident()
        class CompletionBarrier(Fake):
            def __init__(self):
                self.calls, self.err = 0, None

            @property
            def name(self):
                if threading.get_ident() != main_thread:
                    guarded.set()  # completion has passed the generation guard
                    if not resume.wait(2):
                        raise AssertionError("test completion barrier timed out")
                return "Edge"
        engine = CompletionBarrier()
        engine.speak = lambda text, tag, done, audio: callbacks.append(done)
        chain = Chain([engine])
        chain.speak("old", None, lambda err: None)
        worker = threading.Thread(target=lambda: callbacks[0](None))
        worker.start()
        try:
            self.assertTrue(guarded.wait(1))
            chain.speak("new", None, lambda err: None)
        finally:
            resume.set()
            worker.join(2)
        self.assertTrue(chain.busy)
        callbacks[1](None)
        self.assertFalse(chain.busy)

    def test_busy_includes_paused_speech_and_ignores_superseded_completion(self):
        callbacks = []
        engine = Fake("Edge")
        engine.speak = lambda text, tag, done, audio: callbacks.append(done)
        chain = Chain([engine])
        self.assertFalse(chain.busy)
        chain.speak("first", None, lambda err: None)
        chain.pause()
        self.assertTrue(chain.busy)
        chain.speak("second", None, lambda err: None)
        callbacks[0](None)
        self.assertTrue(chain.busy)
        callbacks[1](None)
        self.assertFalse(chain.busy)
        chain.speak("third", None, lambda err: None)
        chain.stop()
        self.assertFalse(chain.busy)

    def test_auto_language_inference_is_preserved_for_codex_and_detected_for_fallbacks(self):
        for requested in (None, "es-ES"):
            with self.subTest(requested=requested):
                codex, edge = Fake("Codex", NoAudioError("offline")), Fake("Edge")
                chain = Chain([codex, edge])
                chain.speak("Hello.", requested, lambda err: None, fallback_tag="he-IL")
                self.assertEqual(codex.tags, [requested])
                self.assertEqual(edge.tags, [requested or "he-IL"])

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
    def test_drain_waits_until_the_output_start_notification_has_been_sent(self):
        p = PcmPlayer.__new__(PcmPlayer)
        p._buf, p._lock, p._width, p._paused = bytearray(), threading.Lock(), 2, threading.Event()
        pending_when_output_is_filled, heard = [], []

        class Output(bytearray):
            def __setitem__(self, key, value):
                pending_when_output_is_filled.append(p.pending)
                super().__setitem__(key, value)

        p.arm(lambda: heard.append(1))
        p.write(array.array("h", [1000] * 4).tobytes())
        p._fill(Output(8), 4, None, None)
        self.assertTrue(all(pending_when_output_is_filled))
        self.assertEqual((p.pending, heard), (False, [1]))

    def test_start_waits_for_voiced_unpaused_output_and_fires_once(self):
        p = PcmPlayer.__new__(PcmPlayer)
        p._buf, p._lock, p._width, p._paused = bytearray(), threading.Lock(), 2, threading.Event()
        heard, out = [], bytearray(8)
        p.arm(lambda: heard.append(1))
        p.write(bytes(8))  # warmup silence is not speech
        p._fill(out, 4, None, None)
        self.assertFalse(heard)
        p._paused.set()
        p.write(array.array("h", [1000] * 8).tobytes())
        p._fill(out, 4, None, None)
        self.assertEqual((heard, bytes(out), len(p._buf)), ([], bytes(8), 16))
        p._paused.clear()
        p._fill(out, 4, None, None)
        p._fill(out, 4, None, None)
        self.assertEqual(heard, [1])

    def test_paused_player_plays_silence_and_keeps_the_queue(self):
        paused = threading.Event()
        p = PcmPlayer.__new__(PcmPlayer)  # no sound device: drive the callback directly
        p._buf, p._lock, p._width, p._paused = bytearray(b"\x01\x02" * 8), threading.Lock(), 2, paused
        p._on_audio = None
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
    def test_auto_update_is_opt_in_and_requires_a_boolean(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            self.assertFalse(settings.load(path)["auto_update"])
            for value, expected in ((True, True), (False, False), ("yes", False), (1, False)):
                settings.save({"auto_update": value}, path)
                self.assertEqual(settings.load(path)["auto_update"], expected)

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

    def test_prefetch_is_off_unless_saved_as_a_boolean(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            self.assertFalse(settings.load(path)["prefetch"])
            for saved, expected in (("true", True), ('"yes"', False), ("1", False)):
                with open(path, "w") as f:
                    f.write('{"prefetch": %s}' % saved)
                self.assertEqual(settings.load(path)["prefetch"], expected, saved)

    def test_startup_round_trip(self):
        name = "codex-speak-unittest"
        try:
            settings.set_startup(True, name)
            self.assertTrue(settings.startup_enabled(name))
            settings.set_startup(False, name)
            self.assertFalse(settings.startup_enabled(name))
            settings.set_startup(False, name)  # already off: no error
        finally:
            settings.set_startup(False, name)


class RenameMigration(unittest.TestCase):
    """Select to TTS became Codex Speak. Its folders and sign-in task move on first start."""

    def dirs(self, d):
        old, new = os.path.join(d, "select-to-tts"), os.path.join(d, "codex-speak")
        os.makedirs(old)
        with open(os.path.join(old, "settings.json"), "w") as f:
            f.write('{"speed": 1.5}')
        return old, new, [(old, new, ("settings.json",))]

    def test_old_folder_moves(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            settings.migrate(dirs)
            self.assertFalse(os.path.exists(old))
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)

    def test_existing_new_folder_is_left_alone(self):
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            os.makedirs(new)
            settings.migrate(dirs)
            self.assertTrue(os.path.exists(os.path.join(old, "settings.json")))
            self.assertEqual(os.listdir(new), [])

    def test_failed_move_copies_settings(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            old, new, dirs = self.dirs(d)
            with patch.object(settings.os, "rename", side_effect=PermissionError):
                settings.migrate(dirs)
            self.assertEqual(settings.load(os.path.join(new, "settings.json"))["speed"], 1.5)

    def test_installed_build_replaces_the_old_task(self):
        from unittest.mock import call, patch
        enabled = {settings.LEGACY_TASK}
        with patch.object(settings.sys, "frozen", True, create=True), \
                patch.object(settings, "startup_enabled", side_effect=lambda name=settings.TASK: name in enabled), \
                patch.object(settings, "set_startup") as set_startup, \
                patch.object(settings.winreg, "OpenKey", side_effect=OSError):
            settings.refresh_startup()
        self.assertEqual(set_startup.call_args_list, [call(True), call(False, settings.LEGACY_TASK)])

    def test_source_run_leaves_the_old_task_alone(self):
        from unittest.mock import patch
        with patch.object(settings.sys, "frozen", False, create=True), \
                patch.object(settings, "startup_enabled", return_value=True), \
                patch.object(settings, "set_startup") as set_startup, \
                patch.object(settings.winreg, "OpenKey", side_effect=OSError):
            settings.refresh_startup()
        set_startup.assert_not_called()


class SttServerRestart(unittest.TestCase):
    def test_restarted_server_keeps_its_url(self):
        from pathlib import Path
        from codex_speak import stt_server
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
