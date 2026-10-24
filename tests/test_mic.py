"""Dictation pieces with no microphone or network: WAV, the tap threshold, the 60 s cap, and the transcript chain."""
import unittest
from unittest.mock import Mock

from harness_discussion import dictation, mic, stt


class FakeStream:
    def __init__(self, cb):
        self.cb, self.started, self.closed = cb, False, False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


class MicTest(unittest.TestCase):
    def test_start_failure_closes_the_created_stream_and_can_be_retried(self):
        stream = Mock()
        stream.start.side_effect = RuntimeError("start failed")
        rec = mic.Recorder(lambda cb: stream)
        with self.assertRaisesRegex(RuntimeError, "start failed"):
            rec.start()
        stream.close.assert_called_once_with()
        self.assertIsNone(rec._stream)
        stream.start.side_effect = None
        rec.start()
        rec.stop()
        self.assertEqual(stream.close.call_count, 2)

    def test_stop_failure_still_closes_and_detaches_stream(self):
        stream = Mock()
        rec = mic.Recorder(lambda cb: stream)
        rec.start()
        stream.stop.side_effect = RuntimeError("stop failed")
        with self.assertRaisesRegex(RuntimeError, "stop failed"):
            rec.stop()
        stream.close.assert_called_once_with()
        self.assertIsNone(rec._stream)
        self.assertEqual(rec.stop(), b"")

    def test_the_wav_is_what_stt_decodes(self):
        pcm = (b"\x10\x00\xf0\xff" * 12000)
        self.assertEqual(stt.decode_audio(mic.wav(pcm)), pcm)

    def test_tap_threshold(self):
        self.assertTrue(mic.is_tap(0.29))
        self.assertFalse(mic.is_tap(0.3))

    def test_recording_stops_at_60_seconds(self):
        streams = []
        rec = mic.Recorder(lambda cb: streams.append(FakeStream(cb)) or streams[-1])
        rec.start()
        second = b"\x01\x00" * mic.RATE
        for _ in range(61):
            streams[0].cb(second, mic.RATE, None, None)
        audio = rec.stop()
        self.assertTrue(streams[0].closed)
        self.assertEqual(len(stt.decode_audio(audio)), mic.MAX_SECONDS * mic.RATE * 2)

    def test_nothing_recorded_is_empty(self):
        rec = mic.Recorder(FakeStream)
        rec.start()
        self.assertEqual(rec.stop(), b"")


class Stt:
    def __init__(self, name, reply="hello", status="ready"):
        self.name, self.reply, self._status, self.calls = name, reply, status, 0

    def status(self):
        return self._status

    def transcribe(self, audio, language=""):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class ChainTest(unittest.TestCase):
    def test_codex_then_cursor_in_order(self):
        codex, cursor = Stt("Codex", RuntimeError("down")), Stt("Cursor", " hi there ")
        self.assertEqual(dictation.transcribe(b"x", [codex, cursor], [["Codex", True], ["Cursor", True]]),
                         ("hi there", "Cursor"))

    def test_disabled_and_not_ready_are_skipped(self):
        codex, cursor = Stt("Codex"), Stt("Cursor", status="signed_out")
        with self.assertRaises(dictation.Error):
            dictation.transcribe(b"x", [codex, cursor], [["Codex", False], ["Cursor", True]])
        self.assertEqual((codex.calls, cursor.calls), (0, 0))

    def test_an_empty_transcript_falls_through(self):
        self.assertEqual(dictation.transcribe(b"x", [Stt("Codex", "  "), Stt("Cursor", "ok")],
                                              [["Codex", True], ["Cursor", True]]), ("ok", "Cursor"))


if __name__ == "__main__":
    unittest.main()
