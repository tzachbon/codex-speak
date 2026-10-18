import asyncio
import sys
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

from codex_speak import stt, stt_server
from codex_speak.codex_rt import AppServer

from stt_helpers import FakePeer, multipart, receive, wav, words


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
