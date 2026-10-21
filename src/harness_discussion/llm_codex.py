"""Codex text turns on the ChatGPT sign-in, for the writer. One app-server per rewrite, closed after."""
import json
import queue
import time

from . import codex_rt
from .writer import Cancelled

SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
          "additionalProperties": False}
MODELS_TTL_S = 600
TIMEOUT_S = 60


class CodexWriter:
    name = "Codex"

    def __init__(self, server=codex_rt.AppServer):
        self._server, self._models, self._models_at = server, None, 0.0

    def status(self):
        return codex_rt.login_status()

    def models(self):
        """[{"id", "efforts"}] for the visible models, cached for 10 minutes."""
        if self._models is None or time.monotonic() - self._models_at > MODELS_TTL_S:
            srv = self._server()
            try:
                data = srv.call("model/list", {}).get("data", [])
            finally:
                srv.close()
            self._models = [{"id": m["id"], "efforts": [e.get("reasoningEffort")
                                                        for e in m.get("supportedReasoningEfforts", [])]}
                            for m in data if not m.get("hidden")]
            self._models_at = time.monotonic()
        return self._models

    def rewrite(self, system, text, model, effort, cancelled):
        srv = self._server({"developerInstructions": system})
        try:
            params = {"threadId": srv.thread_id, "input": [{"type": "text", "text": text}],
                      "approvalPolicy": "never", "sandboxPolicy": {"type": "readOnly"}, "outputSchema": SCHEMA}
            params.update({k: v for k, v in (("model", model), ("effort", effort)) if v})
            turn_id = srv.call("turn/start", params)["turn"]["id"]
            return _final_text(srv, turn_id, cancelled)
        finally:
            srv.close()


def _final_text(srv, turn_id, cancelled):
    final, deadline = None, time.monotonic() + TIMEOUT_S
    while True:
        if cancelled():
            try:
                srv.call("turn/interrupt", {"threadId": srv.thread_id, "turnId": turn_id}, timeout=5)
            except Exception:
                pass  # close() ends the server either way
            raise Cancelled("The rewrite was cancelled.")
        if time.monotonic() > deadline:
            raise TimeoutError("Codex took too long.")
        if not srv.alive:
            raise RuntimeError("codex app-server exited")
        try:
            msg = srv.events.get(timeout=0.2)
        except queue.Empty:
            continue
        method, params = msg.get("method"), msg.get("params") or {}
        if method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
            final = params["item"].get("text")
        elif method == "turn/completed":
            if params.get("turn", {}).get("status") != "completed" or not final:
                raise RuntimeError("Codex did not finish the rewrite.")
            return json.loads(final)["text"]
