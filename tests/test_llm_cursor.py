"""Cursor writer and transcript: the ACP call sequence with a fake agent, and the TranscribeAudio bytes. No network."""
import io
import queue
import unittest
import urllib.error
from unittest import mock

from harness_discussion import llm_cursor, writer


class FakeAcp:
    cwd, alive = "/tmp/empty", True

    def __init__(self, chunks=("Fixed", " text."), stop="end_turn"):
        self.calls, self.notes, self.updates, self._chunks, self.closed = [], [], queue.Queue(), chunks, False
        self.stop = stop

    def call(self, method, params, timeout=20):
        self.calls.append((method, params))
        if method == "session/new":
            return {"sessionId": "s1", "models": {"availableModels": [{"modelId": "gpt[effort=low]", "name": "GPT"}]},
                    "modes": {"availableModes": [{"id": "agent"}, {"id": "ask"}]}}
        if method == "session/prompt":
            for chunk in self._chunks:
                self.updates.put({"method": "session/update", "params": {"sessionId": "s1", "update": {
                    "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": chunk}}}})
            return {"stopReason": self.stop}
        return {}

    def notify(self, method, params):
        self.notes.append((method, params))

    def close(self):
        self.closed = True


class CursorWriterTest(unittest.TestCase):
    def setUp(self):
        self.acp = FakeAcp()
        self.source = llm_cursor.CursorWriter(lambda: self.acp)
        self.addCleanup(self.source.close)

    def test_a_rewrite_uses_ask_mode_the_saved_model_and_joins_the_chunks(self):
        self.assertEqual(self.source.rewrite("SYSTEM", "fixd txt", "gpt[effort=low]", None, lambda: False), "Fixed text.")
        methods = [m for m, _ in self.acp.calls]
        self.assertEqual(methods, ["session/new", "session/set_mode", "session/set_model", "session/prompt"])
        self.assertEqual(self.acp.calls[1][1], {"sessionId": "s1", "modeId": "ask"})
        prompt = self.acp.calls[3][1]["prompt"][0]["text"]
        self.assertTrue(prompt.startswith("SYSTEM"))
        self.assertIn("fixd txt", prompt)

    def test_a_turn_that_ran_out_of_tokens_is_refused(self):
        self.acp.stop = "max_tokens"
        with self.assertRaisesRegex(RuntimeError, "max_tokens"):
            self.source.rewrite("SYSTEM", "long text", None, None, lambda: False)

    def test_the_process_stays_warm_between_rewrites(self):
        starts = []
        source = llm_cursor.CursorWriter(lambda: starts.append(1) or self.acp)
        self.addCleanup(source.close)
        source.rewrite("S", "a", None, None, lambda: False)
        source.rewrite("S", "b", None, None, lambda: False)
        self.assertEqual(len(starts), 1)

    def test_cancel_sends_session_cancel(self):
        with self.assertRaises(writer.Cancelled):
            self.source.rewrite("S", "t", None, None, lambda: True)
        self.assertEqual(self.acp.notes, [("session/cancel", {"sessionId": "s1"})])

    def test_models_come_from_the_session(self):
        self.assertEqual(self.source.models(), [{"id": "gpt[effort=low]", "label": "GPT", "efforts": []}])

    def test_status_reads_cursor_agent_status(self):
        done = mock.Mock(returncode=0, stdout="✓ Logged in as someone\n")
        with mock.patch.object(llm_cursor, "agent_exe", return_value="/x/cursor-agent"), \
                mock.patch.object(llm_cursor.subprocess, "run", return_value=done):
            self.assertEqual(llm_cursor.login_status(), "ready")
            done.stdout = "Not logged in\n"
            self.assertEqual(llm_cursor.login_status(), "signed_out")
        with mock.patch.object(llm_cursor, "agent_exe", return_value=None):
            self.assertEqual(llm_cursor.login_status(), "missing")


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class CursorSttTest(unittest.TestCase):
    def test_request_bytes(self):
        self.assertEqual(llm_cursor.encode_stt(b"RIFF", "audio/wav"), b"\x0a\x04RIFF\x12\x09audio/wav")
        self.assertEqual(llm_cursor.encode_stt(b"A", "audio/wav", "he")[-4:], b"\x1a\x02he")

    def test_reply_text_is_decoded(self):
        sent = []

        def fake_open(req, timeout):
            sent.append(req)
            return _Resp(b"\x0a\x05Hello")
        with mock.patch.object(llm_cursor, "_open", fake_open), \
                mock.patch.object(llm_cursor.cursor_auth, "token", return_value="tok"):
            self.assertEqual(llm_cursor.CursorStt().transcribe(b"RIFF"), "Hello")
        self.assertEqual(sent[0].get_header("Authorization"), "Bearer tok")

    def test_http_errors_name_only_the_code(self):
        err = urllib.error.HTTPError(llm_cursor.STT_URL, 401, "secret body", {}, None)
        with mock.patch.object(llm_cursor, "_open", side_effect=err), \
                mock.patch.object(llm_cursor.cursor_auth, "token", return_value="tok"):
            with self.assertRaisesRegex(llm_cursor.SttError, "^HTTP 401$"):
                llm_cursor.CursorStt().transcribe(b"RIFF")


if __name__ == "__main__":
    unittest.main()
