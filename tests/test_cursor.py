import base64
import io
import json
import logging
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from harness_discussion import cursor_auth, cursor_tts
from harness_discussion.audio import NoAudioError
from harness_discussion.cursor_tts import CursorEngine
from harness_discussion.engines import Chain
from test_edge import FakePlayer, decode_whole, speak, tone_mp3

SECRET = "SECRET-SIGNATURE-0123456789"


def jwt(exp):
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"eyJhbGciOiJIUzI1NiJ9.{payload}.{SECRET}"


class TempDb(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "state.vscdb"
        patcher = mock.patch.object(cursor_auth, "DB", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)

    def store(self, token=None):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)")
        if token is not None:
            con.execute("INSERT INTO ItemTable VALUES ('cursorAuth/accessToken', ?)", (f'"{token}"',))
        con.commit()
        con.close()


class Status(TempDb):
    def test_no_database_is_missing(self):
        self.assertEqual(cursor_auth.status(), "missing")

    def test_no_token_is_signed_out(self):
        self.store()
        self.assertEqual(cursor_auth.status(), "signed_out")

    def test_a_token_expiring_within_a_minute_is_expired(self):
        self.store(jwt(time.time() + 30))
        self.assertEqual(cursor_auth.status(), "expired")
        with self.assertRaises(NoAudioError):
            cursor_auth.token()

    def test_an_undecodable_token_is_expired(self):
        self.store("not-a-jwt")
        self.assertEqual(cursor_auth.status(), "expired")

    def test_a_valid_token_is_ready_and_read_without_quotes(self):
        token = jwt(time.time() + 3600)
        self.store(token)
        self.assertEqual((cursor_auth.status(), cursor_auth.token()), ("ready", token))

    def test_the_database_is_never_changed(self):
        self.store(jwt(time.time() + 3600))
        before = self.db.read_bytes()
        cursor_auth.token()
        self.assertEqual(self.db.read_bytes(), before)


class Encoding(unittest.TestCase):
    def test_long_and_hebrew_text_round_trip(self):
        for text in ("x" * 300, "שלום, זה משפט בעברית שנקרא בקול על ידי Cursor. " * 3):
            fields = cursor_tts.decode(cursor_tts.encode(text, "ara", 1.25))
            self.assertEqual(fields[1].decode(), text)
            self.assertEqual(fields[2], b"ara")
            self.assertEqual(struct.unpack("<f", fields[4])[0], 1.25)

    def test_the_length_is_a_multi_byte_varint(self):
        body = cursor_tts.encode("x" * 300, "ara", 1.0)
        self.assertEqual(body[:3], bytes([0x0A, 0xAC, 0x02]))  # field 1, length 300


def reply(audio, mime=b"audio/mpeg"):
    resp = mock.MagicMock()
    resp.__enter__.return_value = io.BytesIO(cursor_tts._ld(1, audio) + cursor_tts._ld(2, mime))
    return resp


class Synthesize(TempDb):
    def setUp(self):
        super().setUp()
        self.token = jwt(time.time() + 3600)
        self.store(self.token)

    def fails(self, **urlopen):
        with mock.patch.object(urllib.request, "urlopen", **urlopen) as call:
            with self.assertRaises(NoAudioError) as ctx:
                cursor_tts.synthesize("hello", "ara", 1.0)
        self.assertNotIn(SECRET, str(ctx.exception))
        return call

    def test_http_401_timeout_empty_audio_and_wrong_mime_have_no_audio(self):
        self.fails(side_effect=urllib.error.HTTPError(cursor_tts.URL, 401, "Unauthorized", {}, None))
        self.fails(side_effect=TimeoutError())
        self.fails(side_effect=urllib.error.URLError("offline"))
        self.fails(return_value=reply(b""))
        self.fails(return_value=reply(b"\xff\xfb", b"audio/wav"))

    def test_an_expired_sign_in_sends_nothing(self):
        self.store(jwt(time.time() - 10))
        self.fails(return_value=reply(b"\xff\xfb")).assert_not_called()

    def test_the_request_carries_the_sign_in_only_in_its_header(self):
        with mock.patch.object(urllib.request, "urlopen", return_value=reply(b"mp3")) as call:
            self.assertEqual(cursor_tts.synthesize("hello", "luna", 1.5), b"mp3")
        req, kw = call.call_args[0][0], call.call_args[1]
        self.assertEqual(req.get_header("Authorization"), f"Bearer {self.token}")
        self.assertNotIn(SECRET.encode(), req.data)
        self.assertEqual((req.full_url, kw["timeout"]), (cursor_tts.URL, 30))


class Engine(TempDb):
    def setUp(self):
        super().setUp()
        self.store(jwt(time.time() + 3600))
        FakePlayer.opened = []

    def test_a_cursor_mp3_plays_through_the_player(self):
        data = tone_mp3()
        e = CursorEngine()
        e.Player = FakePlayer
        with mock.patch.object(urllib.request, "urlopen", return_value=reply(data)) as call:
            done, result, heard = speak(e)
            self.assertTrue(done.wait(5))
        self.assertEqual((result, len(heard)), ([None], 1))
        self.assertEqual(sum(map(len, FakePlayer.opened[0].writes)), decode_whole(data) * 2)
        self.assertEqual(cursor_tts.decode(call.call_args[0][0].data)[2], b"ara")

    def test_prepare_sends_only_with_text_and_play_joins_it(self):
        e = CursorEngine()
        e.Player = FakePlayer
        with mock.patch.object(urllib.request, "urlopen", return_value=reply(tone_mp3())) as call:
            e.prepare("en-US")
            self.assertFalse(call.called)
            e.prepare("en-US", "hello")
            done, _, _ = speak(e)
            self.assertTrue(done.wait(5))
        self.assertEqual(call.call_count, 1)

    def test_a_failed_read_moves_to_the_next_engine_without_leaking_the_token(self):
        class Next:
            name, speed, paused = "Next", 1.0, threading.Event()
            stop = pause = resume = close = lambda self: None

            def speak(self, text, tag, on_done, on_audio):
                on_done(None)
        cursor, done = CursorEngine(), threading.Event()
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        root, level = logging.getLogger(), logging.getLogger().level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        self.addCleanup(root.setLevel, level)
        self.addCleanup(root.removeHandler, handler)
        chain = Chain([cursor, Next()])
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=urllib.error.HTTPError(cursor_tts.URL, 401, "Unauthorized", {}, None)):
            chain.speak("hello", "en-US", lambda err: done.set())
            self.assertTrue(done.wait(5))
        self.assertEqual(chain.last, "Next")
        self.assertIn("Cursor had no audio", logs.getvalue())
        self.assertNotIn(SECRET, logs.getvalue())

    def test_status_and_voices(self):
        self.assertEqual(CursorEngine().status(), "ready")
        self.assertEqual(len(CursorEngine.voices), 28)
        self.assertIn(("ara", "Ara"), CursorEngine.voices)


if __name__ == "__main__":
    unittest.main()
