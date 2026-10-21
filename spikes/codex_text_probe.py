"""Spike: a plain text rewrite through codex app-server, with a chosen model and effort. Prints timing and event names."""
import json
import sys
import time

from harness_discussion.codex_rt import AppServer

model = (sys.argv[1] if len(sys.argv) > 1 else "") or None
effort = sys.argv[2] if len(sys.argv) > 2 else "low"
t0 = time.monotonic()
srv = AppServer()
try:
    t1 = time.monotonic()
    models = srv.call("model/list", {})
    print("models:", [(m["id"], [e.get("reasoningEffort") for e in m.get("supportedReasoningEfforts", [])])
                      for m in models.get("data", []) if not m.get("hidden")][:8])
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
              "additionalProperties": False}
    srv.call("turn/start", {
        "threadId": srv.thread_id, "model": model, "effort": effort, "approvalPolicy": "never",
        "sandboxPolicy": {"type": "readOnly"}, "outputSchema": schema,
        "input": [{"type": "text", "text": "Fix spelling only. Return the fixed text.\n<<<\ni thinks we should of shiped it\n>>>"}]})
    kinds, final = [], None
    while True:
        msg = srv.events.get(timeout=90)
        method = msg.get("method", "")
        kinds.append(method)
        if method in ("error", "warning") or method.startswith("item/completed"):
            print(method, json.dumps(msg.get("params"))[:300])
        if method == "item/completed" and msg["params"]["item"].get("type") == "agentMessage":
            final = msg["params"]["item"].get("text")
        if method == "turn/completed":
            break
    print("events:", sorted(set(kinds)))
    print("reply:", final and json.loads(final).get("text"))
    print(f"startup {t1 - t0:.1f}s, turn {time.monotonic() - t1:.1f}s")
finally:
    srv.close()
