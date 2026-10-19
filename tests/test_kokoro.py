"""Kokoro: the model download, its status, the reading engine, and where it joins the source order."""
import hashlib
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from harness_discussion import kokoro_tts, settings, sources
from harness_discussion.audio import NoAudioError

from test_core import CoreTest, Engine
from test_edge import FakePlayer

FILES = {"model.onnx": b"model bytes", "voices.bin": b"voice bytes"}


class Reply(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


class Download(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name) / "kokoro"
        self.served, self.requests = dict(FILES), []
        expected = {n: (len(d), hashlib.sha256(d).hexdigest()) for n, d in FILES.items()}
        p = patch.object(kokoro_tts, "FILES", expected)
        p.start()
        self.addCleanup(p.stop)
        self.url = "https://release-assets.githubusercontent.com/x"

    def open(self, request, timeout):
        name = request.full_url.rsplit("/", 1)[1]
        self.requests.append(name)
        return Reply(self.served[name], self.url)

    def download(self):
        with patch.object(kokoro_tts.updates, "urlopen", self.open):
            kokoro_tts.download(self.dir)

    def test_verified_files_are_kept_and_no_partial_file_remains(self):
        self.assertFalse(kokoro_tts.downloaded(self.dir))
        self.download()
        self.assertTrue(kokoro_tts.downloaded(self.dir))
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(FILES))
        self.assertEqual((self.dir / "model.onnx").read_bytes(), FILES["model.onnx"])

    def test_a_file_already_downloaded_is_not_fetched_again(self):
        self.download()
        self.requests.clear()
        (self.dir / "voices.bin").unlink()
        self.download()
        self.assertEqual(self.requests, ["voices.bin"])

    def test_a_wrong_digest_or_size_keeps_nothing(self):
        for bad in (b"model bytez", b"model bytes and more"):
            self.served["model.onnx"] = bad
            with self.assertRaises(ValueError):
                self.download()
            self.assertEqual(os.listdir(self.dir), [])

    def test_a_corrupt_file_of_the_right_size_is_fetched_again(self):
        self.download()
        (self.dir / "model.onnx").write_bytes(b"model bytez")
        self.requests.clear()
        self.download()
        self.assertEqual(self.requests, ["model.onnx"])
        self.assertEqual((self.dir / "model.onnx").read_bytes(), FILES["model.onnx"])

    def test_a_model_that_fails_to_load_drops_only_its_corrupt_files(self):
        self.download()
        (self.dir / "voices.bin").write_bytes(b"voice bytez")
        e = kokoro_tts.KokoroEngine()
        e._load = lambda: (_ for _ in ()).throw(RuntimeError("bad model"))
        done, result = threading.Event(), []
        with patch.object(kokoro_tts, "DIR", self.dir):
            e.speak("Hello.", "en-US", lambda err: (result.append(err), done.set()))
            self.assertTrue(done.wait(5))
            self.assertIsInstance(result[0], NoAudioError)
            self.assertEqual(os.listdir(self.dir), ["model.onnx"])
            self.assertEqual(kokoro_tts.status(), "not_downloaded")

    def test_an_untrusted_download_location_is_refused(self):
        self.url = "https://example.com/model.onnx"
        with self.assertRaisesRegex(ValueError, "location"):
            self.download()
        self.assertEqual(os.listdir(self.dir), [])

    def test_status_follows_the_download(self):
        release, real = threading.Event(), kokoro_tts.download
        with patch.object(kokoro_tts, "DIR", self.dir), patch.object(kokoro_tts.updates, "urlopen", self.open), \
                patch.object(kokoro_tts, "download", lambda d: (release.wait(5), real(d))):
            self.assertEqual(kokoro_tts.status(), "not_downloaded")
            kokoro_tts.start_download()
            kokoro_tts.start_download()  # a second click joins the running download
            self.assertEqual(kokoro_tts.status(), "downloading")
            release.set()
            kokoro_tts._download.join(5)
            self.assertEqual(kokoro_tts.status(), "ready")
        self.assertEqual(self.requests, list(FILES))

    def test_a_failed_download_offers_the_download_again(self):
        self.served["model.onnx"] = b"wrong"
        with patch.object(kokoro_tts, "DIR", self.dir), patch.object(kokoro_tts.updates, "urlopen", self.open), \
                self.assertLogs(kokoro_tts.log, "WARNING"):
            kokoro_tts.start_download()
            kokoro_tts._download.join(5)
            self.assertEqual(kokoro_tts.status(), "not_downloaded")


class FakeModel:
    def __init__(self, fail_at=None, error=RuntimeError("boom")):
        self.calls, self.fail_at, self.error = [], fail_at, error

    def create(self, text, voice, speed, lang):
        self.calls.append((text, voice, speed, lang))
        if len(self.calls) == self.fail_at:
            raise self.error
        return np.array([0.0, 0.5, -1.5], dtype=np.float32), 24000


class Engine_(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        p = patch.object(kokoro_tts, "DIR", Path(folder.name))  # never this computer's real model
        p.start()
        self.addCleanup(p.stop)

    def read(self, text, tag="en-US", model=None, voice=None):
        e = kokoro_tts.KokoroEngine()
        e.Player, e.voice, e.speed = FakePlayer, voice, 1.25
        FakePlayer.opened = []
        e._load = lambda: model if model is not None else (_ for _ in ()).throw(OSError("no model"))
        done, result, heard = threading.Event(), [], []
        e.speak(text, tag, lambda err: (result.append(err), done.set()), lambda: heard.append(1))
        self.assertTrue(done.wait(5))
        return result[0], heard

    def test_reads_sentence_by_sentence_as_16_bit_pcm(self):
        model = FakeModel()
        err, heard = self.read("One. Two!", model=model, voice="bm_george")
        self.assertIsNone(err)
        self.assertEqual(model.calls, [("One.", "bm_george", 1.25, "en-us"), ("Two!", "bm_george", 1.25, "en-us")])
        self.assertEqual(FakePlayer.opened[0].writes[0], np.array([0, 16383, -32767], "<i2").tobytes())
        self.assertEqual((heard, FakePlayer.opened[0].rate, FakePlayer.opened[0].closed), ([1], 24000, True))

    def test_spanish_and_french_use_their_own_voice_and_the_default_is_heart(self):
        for tag, voice, lang in (("es-ES", "ef_dora", "es"), ("fr-FR", "ff_siwis", "fr-fr"),
                                 ("en-US", "af_heart", "en-us")):
            model = FakeModel()
            self.assertIsNone(self.read("Hola.", tag, model)[0])
            self.assertEqual(model.calls[0][1::2], (voice, lang))

    def test_languages_without_a_voice_and_a_missing_model_hand_over_to_the_next_source(self):
        for tag in ("he-IL", "ar-SA", "ru-RU"):
            self.assertIsInstance(self.read("שלום", tag, FakeModel())[0], NoAudioError)
        self.assertIsInstance(self.read("Hello.")[0], NoAudioError)
        self.assertIsInstance(self.read("Hello.", model=FakeModel(fail_at=1))[0], NoAudioError)

    def test_a_sentence_with_nothing_to_say_is_skipped(self):
        model = FakeModel(fail_at=1, error=ValueError("no phonemes"))
        self.assertIsNone(self.read("—. Hello.", model=model)[0])
        self.assertEqual(len(FakePlayer.opened[0].writes), 1)
        self.assertIsInstance(self.read("—.", model=FakeModel(fail_at=1, error=ValueError("x")))[0], NoAudioError)

    def test_an_error_after_speech_started_is_not_handed_over(self):
        err, _ = self.read("One. Two.", model=FakeModel(fail_at=2))
        self.assertIs(type(err), RuntimeError)

    def test_stop_closes_playback_while_the_next_sentence_renders(self):
        release = threading.Event()
        self.addCleanup(release.set)

        class Slow(FakeModel):
            def create(self, *args, **kw):
                if self.calls:
                    release.wait(5)
                return super().create(*args, **kw)
        e = kokoro_tts.KokoroEngine()
        e.Player, e._load = FakePlayer, lambda: Slow()
        FakePlayer.opened = []
        done = threading.Event()
        e.speak("One. Two.", "en-US", lambda err: done.set())
        deadline = time.monotonic() + 5
        while not FakePlayer.opened and time.monotonic() < deadline:
            time.sleep(0.01)
        e.stop()
        self.assertTrue(done.wait(1))
        self.assertTrue(FakePlayer.opened[0].closed)

    def test_voices_are_english_with_a_readable_label(self):
        ids = dict(kokoro_tts.VOICES)
        self.assertEqual((ids["af_heart"], ids["bm_george"]), ("Heart (US)", "George (UK)"))
        self.assertTrue(all(v[:2] in ("af", "am", "bf", "bm") for v in ids))


class Placement(unittest.TestCase):
    def load(self, saved):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            with open(path, "w") as f:
                json.dump(saved, f)
            return [n for n, _ in settings.load(path)["sources"]]

    def test_kokoro_joins_ahead_of_the_system_voices(self):
        system = [n for n in settings.DEFAULT_SOURCES if n in settings.SYSTEM_VOICES]
        self.assertEqual(settings.DEFAULT_SOURCES[2:], ["Kokoro", *system])
        saved = [[n, True] for n in reversed(settings.DEFAULT_SOURCES) if n != "Kokoro"]
        self.assertEqual(self.load({"sources": saved}), ["Kokoro", *reversed(system), "Codex", "Cursor"])
        self.assertEqual(self.load({"sources": [["Codex", True]]}), ["Codex", "Cursor", "Kokoro", *system])

    def test_download_is_the_fix_only_before_the_download(self):
        self.assertEqual(sources.fix("Kokoro", "not_downloaded"), ("Download…", kokoro_tts.start_download))
        for status in ("downloading", "ready", "missing", None):
            self.assertIsNone(sources.fix("Kokoro", status))
        self.assertEqual(settings.status_text("not_downloaded"), "Not downloaded")


class StatusRefresh(CoreTest):
    def test_statuses_are_checked_again_while_the_model_downloads(self):
        app = self.make(Engine("Kokoro"))
        self.host.timers.clear()
        app.statuses = {"Kokoro": "downloading"}
        app._handle("statuses")
        app._handle("statuses")  # a popup or Settings check finished while the poll waits
        self.assertEqual([ms for ms, _ in self.host.timers], [2000])
        with patch.object(app, "refresh_statuses") as refresh:
            self.host.timers[0][1]()
        refresh.assert_called_once()
        app.statuses = {"Kokoro": "ready"}
        app._handle("statuses")
        self.assertEqual(len(self.host.timers), 1)


if __name__ == "__main__":
    unittest.main()
