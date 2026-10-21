"""CodexWriter against a fake app-server: the exact turn/start params, the JSON reply, cancel, and failures."""
import json
import queue
import unittest
from unittest import mock

from harness_discussion import llm_codex, writer


class FakeServer:
    """Records calls. `script` is the list of events to emit after turn/start."""
    made = []

    def __init__(self, thread=None, script=(), models=()):
        self.thread, self.thread_id, self.calls, self.closed = thread, "t1", [], False
        self.events, self.alive, self._script, self._models = queue.Queue(), True, script, models
        FakeServer.made.append(self)

    def call(self, method, params, timeout=20):
        self.calls.append((method, params))
        if method == "turn/start":
            for event in self._script:
                self.events.put(event)
            return {"turn": {"id": "turn9"}}
        if method == "model/list":
            return {"data": list(self._models)}
        return {}

    def close(self):
        self.closed = True


def _reply(text, status="completed"):
    return [{"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": json.dumps({"text": text})}}},
            {"method": "turn/completed", "params": {"turn": {"status": status}}}]


def _writer(**kw):
    FakeServer.made = []
    return llm_codex.CodexWriter(lambda thread=None: FakeServer(thread, **kw))


class CodexWriterTest(unittest.TestCase):
    def test_turn_params_include_model_effort_and_schema(self):
        source = _writer(script=_reply("Fixed."))
        self.assertEqual(source.rewrite("SYSTEM", "fixd", "gpt-5.5", "low", lambda: False), "Fixed.")
        srv = FakeServer.made[0]
        self.assertEqual(srv.thread, {"developerInstructions": "SYSTEM"})
        method, params = srv.calls[0]
        self.assertEqual(method, "turn/start")
        self.assertEqual(params, {"threadId": "t1", "input": [{"type": "text", "text": "fixd"}], "model": "gpt-5.5",
                                  "effort": "low", "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"},
                                  "outputSchema": llm_codex.SCHEMA})
        self.assertTrue(srv.closed)

    def test_no_model_or_effort_uses_the_codex_defaults(self):
        source = _writer(script=_reply("Ok."))
        source.rewrite("S", "ok", None, None, lambda: False)
        params = FakeServer.made[0].calls[0][1]
        self.assertNotIn("model", params)
        self.assertNotIn("effort", params)

    def test_a_failed_turn_raises_and_closes(self):
        source = _writer(script=_reply("x", status="failed"))
        with self.assertRaises(RuntimeError):
            source.rewrite("S", "t", None, None, lambda: False)
        self.assertTrue(FakeServer.made[0].closed)

    def test_cancel_interrupts_the_turn(self):
        source = _writer()
        with self.assertRaises(writer.Cancelled):
            source.rewrite("S", "t", None, None, lambda: True)
        srv = FakeServer.made[0]
        self.assertIn(("turn/interrupt", {"threadId": "t1", "turnId": "turn9"}), srv.calls)
        self.assertTrue(srv.closed)

    def test_timeout(self):
        source = _writer()
        with mock.patch.object(llm_codex, "TIMEOUT_S", 0), self.assertRaises(TimeoutError):
            source.rewrite("S", "t", None, None, lambda: False)

    def test_models_are_visible_only_and_cached(self):
        models = [{"id": "a", "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "high"}]},
                  {"id": "b", "hidden": True}]
        source = _writer(models=models)
        self.assertEqual(source.models(), [{"id": "a", "efforts": ["low", "high"]}])
        source.models()
        self.assertEqual(len(FakeServer.made), 1)
        self.assertTrue(FakeServer.made[0].closed)


if __name__ == "__main__":
    unittest.main()
