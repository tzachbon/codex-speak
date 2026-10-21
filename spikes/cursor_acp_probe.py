"""Spike: rewrite through a warm `cursor-agent acp` process. Prints timings, models offered, and the reply."""
import json
import subprocess
import sys
import tempfile
import threading
import queue
import time

model = sys.argv[1] if len(sys.argv) > 1 else ""
p = subprocess.Popen(["cursor-agent", "acp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
inbox, pending, ids = queue.Queue(), {}, [0]


def reader():
    for line in p.stdout:
        msg = json.loads(line)
        if "id" in msg and "method" in msg:  # permission or other client request: refuse
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "no"}}) + "\n")
            p.stdin.flush()
        elif msg.get("id") in pending:
            pending.pop(msg["id"]).put(msg)
        else:
            inbox.put(msg)


threading.Thread(target=reader, daemon=True).start()


def call(method, params, timeout=120):
    ids[0] += 1
    box = pending[ids[0]] = queue.Queue()
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": ids[0], "method": method, "params": params}) + "\n")
    p.stdin.flush()
    msg = box.get(timeout=timeout)
    if "error" in msg:
        raise RuntimeError(f"{method}: {msg['error']}")
    return msg["result"]


t0 = time.monotonic()
call("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
cwd = tempfile.mkdtemp()
session = call("session/new", {"cwd": cwd, "mcpServers": []})
sid = session["sessionId"]
print("session keys:", sorted(session))
models = (session.get("models") or {}).get("availableModels", [])
print("models:", [m.get("modelId") for m in models][:10], "current:", (session.get("models") or {}).get("currentModelId"))
print("modes:", [m.get("id") for m in (session.get("modes") or {}).get("availableModes", [])])
if model:
    call("session/set_model", {"sessionId": sid, "modelId": model})
t1 = time.monotonic()
for text in ["i thinks we should of shiped it", "can u send me the numbers by eod thx"]:
    while not inbox.empty():
        inbox.get()
    t = time.monotonic()
    call("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text":
         f"Fix spelling and grammar only. Reply with only the fixed text.\n<<<\n{text}\n>>>"}]})
    out = []
    while not inbox.empty():
        u = inbox.get().get("params", {}).get("update", {})
        if u.get("sessionUpdate") == "agent_message_chunk":
            out.append(u.get("content", {}).get("text", ""))
    print(f"prompt {time.monotonic() - t:.1f}s:", "".join(out))
print(f"startup {t1 - t0:.1f}s")
p.kill()
