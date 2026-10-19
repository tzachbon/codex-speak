import array
import asyncio
import math
import os
import queue
import tempfile
import threading
import unittest
from unittest import mock

import sys

from harness_discussion import lang, settings
from harness_discussion.audio import NoAudioError, Stretcher
from harness_discussion.clicks import Clicks
from harness_discussion.codex_rt import ATTEMPTS, CodexEngine, Silent
from harness_discussion.engines import Chain, EdgeEngine


class Lang(unittest.TestCase):
    def test_reading_rtl_follows_the_first_strong_character(self):
        self.assertTrue(lang.reading_rtl("123 שלום world"))
        self.assertFalse(lang.reading_rtl("hello שלום"))
        self.assertFalse(lang.reading_rtl("123 ..."))

    def test_detect(self):
        self.assertEqual(lang.detect("שלום עולם"), "he-IL")
        self.assertEqual(lang.detect("hello world"), "en-US")
        self.assertEqual(lang.detect("שלום hello עולם"), "he-IL")
        self.assertEqual(lang.detect("Привет мир"), "ru-RU")
        self.assertEqual(lang.detect("مرحبا بالعالم"), "ar-SA")
        self.assertEqual(lang.detect("123"), "en-US")


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


class ClicksTest(unittest.TestCase):
    def test_drag_and_double_click(self):
        c, hits = Clicks(0.5), []
        def click(x, y, t):
            c.down(x, y)
            return c.up(x, y, t)
        c.down(0, 0)
        hits.append(c.up(100, 0, 1.0))  # drag
        hits.append(click(500, 500, 2.0))  # single click: nothing
        hits.append(click(500, 500, 2.2))  # second click: double-click
        hits.append(click(500, 500, 3.0))  # too late for a double-click
        hits.append(click(510, 500, 3.1))  # moved too far between clicks
        self.assertEqual(hits, [True, False, True, False, False])


def _no_audio(cause):
    err = NoAudioError(f"Codex: {cause}")
    err.__cause__ = cause
    return err


class CodexRetry(unittest.TestCase):
    def read(self, *outcomes):
        engine = CodexEngine()
        self.addCleanup(engine.close)
        engine._srv = mock.Mock(alive=True)
        with mock.patch.object(engine, "_read_aloud", mock.AsyncMock(side_effect=outcomes)) as read_aloud:
            future = asyncio.run_coroutine_threadsafe(engine._speak(None, None), engine._loop)
            try:
                future.result(5)
                err = None
            except NoAudioError as e:
                err = e
        return read_aloud.await_count, err

    def test_a_silent_session_is_retried_in_a_fresh_one(self):
        self.assertEqual(self.read(_no_audio(Silent("x")), _no_audio(Silent("x")), None), (3, None))

    def test_gives_up_after_the_last_attempt(self):
        count, err = self.read(*[_no_audio(Silent("x"))] * ATTEMPTS)
        self.assertEqual(count, ATTEMPTS)
        self.assertIsInstance(err.__cause__, Silent)

    def test_other_failures_are_not_retried(self):
        count, err = self.read(_no_audio(RuntimeError("thread/start failed")))
        self.assertEqual(count, 1)
        self.assertIsInstance(err.__cause__, RuntimeError)


class CodexSessionEvents(unittest.TestCase):
    def test_a_cancelled_session_that_starts_late_does_not_answer_for_the_next(self):
        engine = CodexEngine()
        self.addCleanup(engine.close)
        srv = mock.Mock(alive=True, events=queue.Queue())
        for session in ("old", "new"):  # the old one was stopped while starting
            for method, params in [("started", {"realtimeSessionId": session}), ("sdp", {"sdp": session}),
                                   ("closed", {"reason": "requested"})]:
                srv.events.put({"method": "thread/realtime/" + method, "params": params})

        async def answer():
            await engine._next_event(srv, "thread/realtime/started", 5, "new")
            return (await engine._next_event(srv, "thread/realtime/sdp", 5))["sdp"]
        self.assertEqual(asyncio.run_coroutine_threadsafe(answer(), engine._loop).result(10), "new")

    def test_captions_follow_the_voice_transcript_only(self):
        engine = CodexEngine()
        self.addCleanup(engine.close)
        srv = mock.Mock(alive=True, events=queue.Queue())
        for method, params in [("delta", {"role": "user", "delta": "Read it."}),
                               ("delta", {"role": "assistant", "delta": "Hel"}),
                               ("delta", {"role": "assistant", "delta": "lo"}),
                               ("done", {"role": "user", "text": "Read it."}),
                               ("done", {"role": "assistant", "text": "Hello"})]:
            srv.events.put({"method": "thread/realtime/transcript/" + method, "params": params})
        seen = []
        asyncio.run_coroutine_threadsafe(engine._follow_transcript(srv, seen.append), engine._loop).result(10)
        self.assertEqual(seen, ["Hel", "Hello"])


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
            self.assertEqual(settings.load(path)["auto_update"], sys.platform == "darwin")  # opt-in on Windows
            default = settings.DEFAULTS["auto_update"]
            for value, expected in ((True, True), (False, False), ("yes", default), (1, default)):
                settings.save({"auto_update": value}, path)
                self.assertEqual(settings.load(path)["auto_update"], expected)

    def test_load_defaults_clamps_and_survives_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "settings.json")
            self.assertEqual(settings.load(path), settings.DEFAULTS)
            settings.save({"voices": {"Cursor": "eve"}, "speed": 9, "clipboard_fallback": False}, path)
            self.assertEqual(settings.load(path), {**settings.DEFAULTS, "voices": {"Cursor": "eve"}, "speed": 2.0,
                                                   "clipboard_fallback": False})
            for junk in ("{not json", "[1, 2]", "null", '{"engine": "Bogus", "speed": "fast"}',
                         '{"speed": NaN, "clipboard_fallback": "false"}', '{"speed": true, "engine": 3}', '{"speed": 1' + '0' * 400 + '}'):
                with open(path, "w") as f:
                    f.write(junk)
                self.assertEqual(settings.load(path), settings.DEFAULTS)

    def test_source_names_are_per_platform(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            other = "Windows" if sys.platform == "darwin" else "macOS"
            settings.save({"engine": other, "sources": [[other, True]]}, path)
            self.assertEqual(settings.load(path)["sources"], settings.DEFAULTS["sources"])

    def test_ax_granted_build_is_a_string_or_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            for saved, expected in (("0.6.0+abc", "0.6.0+abc"), (3, None), (None, None)):
                settings.save({"ax_granted_build": saved}, path)
                self.assertEqual(settings.load(path)["ax_granted_build"], expected)

    def test_prefetch_is_off_unless_saved_as_a_boolean(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            self.assertFalse(settings.load(path)["prefetch"])
            for saved, expected in (("true", True), ('"yes"', False), ("1", False)):
                with open(path, "w") as f:
                    f.write('{"prefetch": %s}' % saved)
                self.assertEqual(settings.load(path)["prefetch"], expected, saved)



class SttServerRestart(unittest.TestCase):
    def test_restarted_server_keeps_its_url(self):
        from pathlib import Path
        from harness_discussion import stt_server
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



if __name__ == "__main__":
    unittest.main()
