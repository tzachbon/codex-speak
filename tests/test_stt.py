import asyncio
from http.client import HTTPConnection
import io
import json
import os
import queue
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import wave

import av

from select_to_tts import stt, stt_server
from select_to_tts.codex_rt import AppServer


def wav(seconds=0.1):
    output = io.BytesIO()
    with wave.open(output, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * int(24000 * seconds))
    return output.getvalue()


class FakePeer:
    """Stands in for aiortc: always connected, pulls frames from the track, and plays scripted events."""
    connectionState = "connected"
    localDescription = MagicMock(sdp="")

    def __init__(self, script):
        self.script, self.handler = script, None

    def addTrack(self, track):
        self.track = track

    def createDataChannel(self, name):
        peer = self
        class Channel:
            def on(self, event):
                def register(handler):
                    peer.handler = handler
                    return handler
                return register
        return Channel()

    async def createOffer(self):
        return None

    async def setLocalDescription(self, description):
        pass

    async def close(self):
        pass

    async def play(self):
        while not self.track.finished_at:
            await self.track.recv()
        for delay, event in self.script:  # Delays are seconds after the audio finished sending.
            await asyncio.sleep(delay)
            self.handler(json.dumps(event(self.track)))


def receive(script, seconds=2.0):
    """Runs _receive against FakePeer. Returns (text or SttError, diag)."""
    peer, diag = FakePeer(script), {"started": time.monotonic(), "stage": "connect", "marks": {}, "events": {}}
    srv = MagicMock(alive=True, events=queue.Queue())
    async def run():
        player = None
        with patch.object(stt, "RTCPeerConnection", return_value=peer):
            task = asyncio.ensure_future(stt._receive(srv, b"\0\0" * int(stt.RATE * seconds), "", "", diag))
            await asyncio.sleep(0)
            player = asyncio.ensure_future(peer.play())
            try:
                return await task
            except stt.SttError as error:
                return error
            finally:
                player.cancel()
    return asyncio.run(run()), diag


def words(text, end_ms):
    return lambda track: {"type": "input_transcript.added", "item": {"text": text}, "end_ms": end_ms(track)}


def multipart(audio, **fields):
    body = b'--probe\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n' + audio + b"\r\n"
    for name, value in fields.items():
        body += f'--probe\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    return body + b"--probe--\r\n"


class Module(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        log = patch.object(stt, "DIAG_LOG", Path(folder.name) / "diag.log")
        log.start()
        self.addCleanup(log.stop)

    def test_decode_and_limits(self):
        self.assertEqual(len(stt.decode_audio(wav())), 4800)
        for data in (b"", b"#EXTM3U\nhttp://localhost/private", b"RIFF0000WAVEbad", wav(61)):
            with self.assertRaises(ValueError):
                stt.decode_audio(data)

    def test_webm_input(self):
        output = io.BytesIO()
        with av.open(output, "w", format="webm") as media:
            stream = media.add_stream("libopus", rate=24000)
            stream.layout = "mono"
            frame = av.AudioFrame(format="s16", layout="mono", samples=2400)
            frame.planes[0].update(b"\0" * 4800)
            frame.sample_rate = 24000
            for packet in stream.encode(frame):
                media.mux(packet)
            for packet in stream.encode(None):
                media.mux(packet)
        self.assertGreater(len(stt.decode_audio(output.getvalue())), 0)

    def test_busy_does_not_decode(self):
        stt._busy.acquire()
        try:
            with patch.object(stt, "decode_audio") as decode, self.assertRaises(stt.BusyError):
                stt.transcribe(wav())
            decode.assert_not_called()
        finally:
            stt._busy.release()

    def test_backend_failure_reaps_and_releases(self):
        with patch.object(stt, "AppServer") as server, patch.object(stt, "_receive", side_effect=RuntimeError("failed")):
            with self.assertRaises(RuntimeError):
                stt.transcribe(wav())
            server.return_value.close.assert_called_once()
        self.assertFalse(stt._busy.locked())

    def test_failures_are_classified_and_logged_without_content(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(stt, "DIAG_LOG", Path(folder) / "diag.log"):
            with patch.object(stt, "AppServer", side_effect=RuntimeError("thread/start: sk-secret said hello")):
                with self.assertRaises(stt.SttError) as caught:
                    stt.transcribe(wav())
            self.assertEqual((caught.exception.code, caught.exception.stage), ("backend_start_failed", "backend_start"))
            with patch.object(stt, "AppServer") as server, patch.object(stt, "_receive", side_effect=TimeoutError("hello")):
                server.return_value.close.side_effect = OSError("teardown sk-secret")
                with self.assertRaises(stt.SttError) as caught:
                    stt.transcribe(wav())
            self.assertEqual(caught.exception.code, "completion_timeout")
            self.assertFalse(stt._busy.locked())
            records = [json.loads(line) for line in (Path(folder) / "diag.log").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["code"] for r in records], ["backend_start_failed", "completion_timeout"])
        self.assertEqual(records[1]["id"], caught.exception.request_id)
        self.assertEqual(records[1]["audio_ms"], 100)
        text = json.dumps(records)
        self.assertNotIn("secret", text)
        self.assertNotIn("hello", text)

    def test_peer_teardown_failure_keeps_primary_error(self):
        pc = MagicMock()
        pc.createOffer, pc.setLocalDescription = AsyncMock(), AsyncMock()
        pc.close = AsyncMock(side_effect=OSError("close failed"))
        srv = MagicMock()
        srv.call.side_effect = RuntimeError("start failed")
        diag = {"started": 0, "stage": "connect", "marks": {}, "events": {}}
        with patch.object(stt, "RTCPeerConnection", return_value=pc), self.assertRaises(stt.SttError) as caught:
            asyncio.run(stt._receive(srv, b"\0\0" * 480, "", "", diag))
        self.assertEqual(caught.exception.code, "realtime_start_failed")
        self.assertEqual(diag["peer_teardown_error"], "OSError")

    def test_rejected_calls_are_logged(self):
        with self.assertRaises(ValueError):
            stt.transcribe(wav(), prompt="x" * 3000)
        stt._busy.acquire()
        try:
            with self.assertRaises(stt.BusyError):
                stt.transcribe(wav())
        finally:
            stt._busy.release()
        records = [json.loads(line) for line in stt.DIAG_LOG.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["code"] for r in records], ["invalid_input", "busy"])
        self.assertFalse(stt._busy.locked())

    def test_diagnostics_rotate_and_never_fail(self):
        stt.DIAG_LOG.write_text("x" * (1 << 20 + 1), encoding="utf-8")
        stt._write_diag({"code": "ok"})
        self.assertEqual(stt.DIAG_LOG.read_text(encoding="utf-8"), '{"code": "ok"}\n')
        self.assertTrue(stt.DIAG_LOG.with_name(stt.DIAG_LOG.name + ".1").exists())
        with patch.object(stt, "DIAG_LOG", stt.DIAG_LOG.parent):  # a directory cannot be appended to
            stt._write_diag({"code": "ok"})

    def test_concurrent_rotation_keeps_every_record(self):
        stt.DIAG_LOG.write_text("x" * (2 << 20), encoding="utf-8")
        real_replace = os.replace
        def slow_replace(*args):
            time.sleep(0.05)
            real_replace(*args)
        with patch.object(stt.os, "replace", side_effect=slow_replace):
            writers = [threading.Thread(target=stt._write_diag, args=({"n": n},)) for n in range(3)]
            for writer in writers:
                writer.start()
            for writer in writers:
                writer.join(5)
        self.assertEqual(len(stt.DIAG_LOG.read_text(encoding="utf-8").splitlines()), 3)

    def test_track_sends_ahead_with_real_time_stamps(self):
        async def send():
            track = stt._AudioTrack(bytes(2) * stt.RATE)  # One second of audio.
            track.ready, started = True, time.monotonic()
            while not track.finished_at:
                frame = await track.recv()
            return track, frame, time.monotonic() - started
        track, frame, elapsed = asyncio.run(send())
        self.assertLess(elapsed, 0.9)  # Paced at 4x (0.25 s), not 1x (1 s).
        self.assertEqual((frame.pts, track.end_ms), (stt.RATE - 480, 1000))

    def test_settle_waits_for_late_words(self):
        # Measured worst case: last word 1.2 s after audio end, 1.1 s between words.
        self.assertFalse(stt._settled(since_audio_end=2.0, since_last_word=5.0))
        self.assertFalse(stt._settled(since_audio_end=3.0, since_last_word=1.5))
        self.assertTrue(stt._settled(since_audio_end=2.5, since_last_word=2.0))
        self.assertTrue(stt._settled(since_audio_end=3.0, since_last_word=None))
        self.assertTrue(stt._settled(since_audio_end=12.0, since_last_word=0.1))
        # Sending ahead of real time leaves Codex more audio to finish, so the cap grows with length.
        self.assertFalse(stt._settled(since_audio_end=12.0, since_last_word=0.1, audio_seconds=20))
        self.assertTrue(stt._settled(since_audio_end=27.0, since_last_word=0.1, audio_seconds=20))
        # No fragment yet, or Codex far behind: wait as long as a 1x send would have.
        self.assertFalse(stt._settled(since_audio_end=17.0, since_last_word=None, audio_seconds=20))
        self.assertTrue(stt._settled(since_audio_end=17.5, since_last_word=None, audio_seconds=20))
        self.assertFalse(stt._settled(since_audio_end=5.0, since_last_word=4.0, audio_seconds=20, unheard=8.0))
        self.assertTrue(stt._settled(since_audio_end=5.0, since_last_word=11.0, audio_seconds=20, unheard=8.0))
        # Near the end, the quiet gap covers the unheard audio plus clock skew.
        self.assertFalse(stt._settled(since_audio_end=3.0, since_last_word=2.9, audio_seconds=20, unheard=0.0))
        self.assertTrue(stt._settled(since_audio_end=3.0, since_last_word=3.0, audio_seconds=20, unheard=-0.6))
        self.assertFalse(stt._settled(since_audio_end=4.0, since_last_word=3.9, audio_seconds=20, unheard=1.0))
        # A position far past the audio end is implausible, so it is not trusted.
        self.assertFalse(stt._settled(since_audio_end=9.0, since_last_word=9.0, audio_seconds=20, unheard=-5.0))

    def test_late_word_after_skewed_position_is_kept(self):
        # Codex reports a position 0.6 s past the truth, then the last word arrives 2.9 s later.
        result, diag = receive([(0.1, words("first ", lambda t: t.end_ms - 500)),
                                (2.9, words("last", lambda t: t.end_ms))])
        self.assertEqual(result, "first last")
        self.assertEqual(diag["fragments"], 2)

    def test_invalid_positions_fail_and_keep_progress(self):
        result, diag = receive([(0.0, words("x", lambda t: 10 ** 400))], seconds=0.2)
        self.assertEqual((result, diag["heard_end_ms"]), ("x", 10 ** 7))  # Untrusted, so the slow path.
        for bad in (True, -1, "100"):
            result, diag = receive([(0.0, words("first ", lambda t: 100)), (0.0, words("x", lambda t: bad))], seconds=0.2)
            self.assertEqual(result.code, "invalid_event")
            self.assertEqual((diag["fragments"], diag["heard_end_ms"]), (1, 100))
            self.assertIsNotNone(diag["stream_end_ms"])

    def test_failed_init_reaps_process(self):
        with patch("select_to_tts.codex_rt.codex_exe", return_value="codex"), patch("select_to_tts.codex_rt.subprocess.Popen") as popen, patch("select_to_tts.codex_rt.subprocess.run"), patch("select_to_tts.codex_rt.threading.Thread"), patch.object(AppServer, "call", side_effect=RuntimeError("init failed")):
            popen.return_value.poll.return_value = None
            with self.assertRaises(RuntimeError):
                AppServer()
            popen.return_value.kill.assert_called_once()
            popen.return_value.wait.assert_called_once_with(timeout=5)

    def test_malformed_duplicate_form_fields(self):
        body = multipart(wav(), model=stt.MODEL)
        body = body.replace(b"--probe--", b'--probe\r\nContent-Disposition: form-data; name="model"\r\n\r\nother\r\n--probe--')
        with self.assertRaises(ValueError):
            stt_server.parse_form("multipart/form-data; boundary=probe", body)


class Http(unittest.TestCase):
    def setUp(self):
        self.server = stt_server.SttServer(0)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.backend = patch.object(stt_server, "transcribe", return_value="hello")
        self.mock = self.backend.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.backend.stop()

    def request(self, body=b"", headers=None, suffix="/audio/transcriptions", method="POST", token=None):
        conn = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        conn.request(method, f"/{self.server.token if token is None else token}/v1{suffix}", body=body,
                     headers=headers or {"Content-Type": "multipart/form-data; boundary=probe"})
        response = conn.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return result

    def test_multipart_json_text_and_models(self):
        status, body, headers = self.request(multipart(wav(), model=stt.MODEL, language="en"))
        self.assertEqual((status, json.loads(body)), (200, {"text": "hello"}))
        self.mock.assert_called_once_with(wav(), language="en", prompt="")
        self.assertEqual(self.request(multipart(wav(), response_format="text"))[:2], (200, b"hello"))
        status, body, _ = self.request(method="GET", suffix="/models")
        self.assertEqual(json.loads(body)["data"][0]["id"], stt.MODEL)

    def test_port_cannot_be_shared(self):
        with self.assertRaises(OSError):
            other = stt_server.SttServer(self.server.server_port)
            other.server_close()

    def test_access_checks_and_bad_input_do_not_call_backend(self):
        self.assertEqual(self.request(token="wrong")[0], 403)
        self.assertEqual(self.request(headers={"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.request(headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request(headers={"Content-Length": str(stt_server.MAX_BODY + 1)})[0], 413)
        self.assertEqual(self.request(b"bad")[0], 400)
        self.assertEqual(self.request(multipart(wav(), response_format="srt"))[0], 400)
        self.assertEqual(self.request(multipart(wav(), model="unknown"))[0], 400)
        self.mock.assert_not_called()

    def test_busy_before_body_read_and_origin_null(self):
        self.server.busy.acquire()
        try:
            self.assertEqual(self.request(headers={"Content-Length": "100"})[0], 429)
        finally:
            self.server.busy.release()
        status, _, headers = self.request(multipart(wav()), headers={"Origin": "null", "Content-Type": "multipart/form-data; boundary=probe"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "null")

    def test_backend_failure_is_classified_without_leaking(self):
        self.mock.side_effect = stt.SttError("no_transcript", "collect", "abc123")
        status, body, _ = self.request(multipart(wav()))
        error = json.loads(body)["error"]
        self.assertEqual((status, error["code"], error["request_id"]), (502, "no_transcript", "abc123"))
        self.assertNotIn("login", error["message"].lower())
        self.mock.side_effect = RuntimeError("sk-secret-token said hello world")
        status, body, _ = self.request(multipart(wav()))
        error = json.loads(body)["error"]
        self.assertEqual((status, error["code"], bool(error["request_id"])), (502, "unknown", True))
        self.assertNotIn(b"secret", body)
        self.mock.side_effect = stt.SttError("completion_timeout", "collect", "abc124")
        status, body, _ = self.request(multipart(wav()))
        self.assertEqual((status, json.loads(body)["error"]["code"]), (504, "completion_timeout"))
        self.mock.side_effect = None
        self.assertEqual(self.request(multipart(wav()))[0], 200)

    def test_startup_timeouts_keep_http_504(self):
        self.mock.side_effect = stt.transcribe
        with tempfile.TemporaryDirectory() as folder, patch.object(stt, "DIAG_LOG", Path(folder) / "diag.log"), \
                patch.object(stt, "AppServer") as backend, patch.object(stt, "RTCPeerConnection") as peer:
            pc = peer.return_value
            pc.createOffer, pc.setLocalDescription, pc.close = AsyncMock(), AsyncMock(), AsyncMock()
            for stage in ("backend_start", "realtime_start"):
                for failure in (queue.Empty("private backend text"), TimeoutError("private backend text")):
                    with self.subTest(stage=stage, failure=type(failure).__name__):
                        backend.side_effect = failure if stage == "backend_start" else None
                        backend.return_value.call.side_effect = failure
                        status, body, _ = self.request(multipart(wav()))
                        error = json.loads(body)["error"]
                        self.assertEqual((status, error["code"]), (504, stage + "_failed"))
                        self.assertTrue(error["request_id"])
                        self.assertNotIn(b"private backend text", body)
                        self.assertFalse(stt._busy.locked())

    def test_close_waits_for_active_handler(self):
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            started.set()
            release.wait(3)
            return "hello"
        self.mock.side_effect = blocked
        request = threading.Thread(target=lambda: self.request(multipart(wav())))
        request.start()
        self.assertTrue(started.wait(2))
        self.server.shutdown()
        closer = threading.Thread(target=lambda: (self.server.server_close(), closed.set()))
        closer.start()
        try:
            self.assertFalse(closed.wait(0.1))
        finally:
            release.set()
            request.join(3)
            closer.join(3)
        self.assertTrue(closed.is_set())


@unittest.skipUnless(os.environ.get("STT_LIVE_CHECK") == "1", "Explicit subscription-backed live check")
class LiveHttp(unittest.TestCase):
    def test_english_webm_through_http(self):
        root = Path(__file__).resolve().parents[1]
        fixture = root / "spikes/out/en_S2_0.wav"
        output = io.BytesIO()
        with av.open(str(fixture)) as source, av.open(output, "w", format="webm") as target:
            stream = target.add_stream("libopus", rate=24000)
            stream.layout = "mono"
            for frame in source.decode(audio=0):
                for packet in stream.encode(frame):
                    target.mux(packet)
            for packet in stream.encode(None):
                target.mux(packet)
        with stt_server.SttServer(0) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=120)
            try:
                connection.request("POST", f"/{server.token}/v1/audio/transcriptions",
                    body=multipart(output.getvalue(), model=stt.MODEL),
                    headers={"Origin": "null", "Content-Type": "multipart/form-data; boundary=probe"})
                response = connection.getresponse()
                result = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertTrue(result.get("text"))
                # Reference is consulted only after receiving the audio-only request's result.
                import importlib.util
                spec = importlib.util.spec_from_file_location("probe", root / "spikes/stt_prototype.py")
                probe = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(probe)
                records = json.loads(fixture.with_name("results.json").read_text(encoding="utf-8"))
                reference = next(r["transcript"] for r in records if (r["fixture"], r["strategy"], r["n"]) == ("en", "S2", 0))
                wer = probe.word_error_rate(reference, result["text"])
                print(f"Live WebM HTTP result: status=200, WER={wer:.3f}")
                self.assertLessEqual(wer, 0.1)
            finally:
                connection.close()
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
