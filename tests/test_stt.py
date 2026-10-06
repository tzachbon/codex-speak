from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
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


def multipart(audio, **fields):
    body = b'--probe\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n' + audio + b"\r\n"
    for name, value in fields.items():
        body += f'--probe\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    return body + b"--probe--\r\n"


class Module(unittest.TestCase):
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
