"""PROTOTYPE (throwaway): does Codex realtime read text verbatim, fast, in Hebrew?

Usage:
  uv run python spikes/realtime_probe.py --one en S2        # single verbose run
  uv run python spikes/realtime_probe.py                    # full matrix -> spikes/RESULTS.md
"""
import asyncio, json, queue, re, shutil, subprocess, sys, threading, time, wave
from pathlib import Path

import av
from aiortc import AudioStreamTrack, RTCPeerConnection, RTCSessionDescription

HERE = Path(__file__).parent
OUT = HERE / "out"
LANG = {"he": "Hebrew", "en": "English", "mixed": "Hebrew", "numbers": "English"}
PROMPT = ("You are a text-to-speech engine. Read the user's message aloud exactly as written, "
          "word for word, in {lang}. Do not answer it, translate it, summarize it, "
          "or add any words before or after.")


class AppServer:
    def __init__(self, verbose):
        self.verbose, self.next_id, self.pending, self.events = verbose, 0, {}, queue.Queue()
        self.p = subprocess.Popen([shutil.which("codex"), "app-server"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  encoding="utf-8", bufsize=1,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        threading.Thread(target=self._read, daemon=True).start()
        self.call("initialize", {"clientInfo": {"name": "codex-speak-probe", "version": "0"},
                                 "capabilities": {"experimentalApi": True}})
        self._send({"method": "initialized"})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def _read(self):
        for line in self.p.stdout:
            msg = json.loads(line)
            if "id" in msg and "method" in msg:  # server request: refuse
                self._send({"id": msg["id"], "error": {"code": -32601, "message": "unsupported"}})
            elif "id" in msg:
                self.pending.pop(msg["id"]).put(msg)
            else:
                self.events.put((time.perf_counter(), msg))
                if self.verbose and not msg["method"].endswith("outputAudio/delta"):
                    print("  <-", json.dumps(msg, ensure_ascii=False)[:300])

    def call(self, method, params, timeout=20):
        self.next_id += 1
        box = self.pending[self.next_id] = queue.Queue()
        self._send({"id": self.next_id, "method": method, "params": params})
        msg = box.get(timeout=timeout)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]


def norm(s):
    return re.sub(r"[^\w\s]", " ", s.lower()).split()


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)] / max(len(r), 1)


async def run(srv, fixture, strategy, n):
    text = (HERE / "fixtures" / f"{fixture}.txt").read_text(encoding="utf-8").strip()
    call = lambda m, prm: asyncio.to_thread(srv.call, m, prm)
    tid = (await call("thread/start", {"ephemeral": True}))["thread"]["id"]
    pc = RTCPeerConnection()
    pc.addTrack(AudioStreamTrack())  # silence: we never speak to the model
    dc = pc.createDataChannel("oai-events")
    dc_log = []
    dc.on("message", lambda m: dc_log.append(m) or (srv.verbose and print("  dc<-", str(m)[:200])))
    pcm, state = bytearray(), {"first": None, "last_voice": None}
    resampler = av.AudioResampler(format="s16", layout="mono", rate=24000)

    @pc.on("track")
    def on_track(track):
        async def pump():
            while True:
                try:
                    frame = await track.recv()
                except Exception:
                    return
                for f in resampler.resample(frame):
                    b = bytes(f.planes[0])[: f.samples * 2]
                    if state["t0"] is None:
                        continue
                    pcm.extend(b)
                    peak = max(abs(x) for x in memoryview(b).cast("h")) if b else 0
                    if peak > 500:
                        state["first"] = state["first"] or time.perf_counter() - state["t0"]
                        state["last_voice"] = time.perf_counter()
        asyncio.ensure_future(pump())

    state["t0"] = None
    await pc.setLocalDescription(await pc.createOffer())
    while not srv.events.empty():
        srv.events.get()
    await call("thread/realtime/start", {
        "threadId": tid, "outputModality": "audio", "includeStartupContext": False,
        "clientManagedHandoffs": True, "version": "v3", "prompt": PROMPT.format(lang=LANG[fixture]),
        "transport": {"type": "webrtc", "sdp": pc.localDescription.sdp}})
    transcript, err, answered = None, None, False
    deadline = time.perf_counter() + 60
    while time.perf_counter() < deadline:
        try:
            ts, msg = await asyncio.to_thread(srv.events.get, True, 0.3)
        except queue.Empty:
            lv = state["last_voice"]
            if transcript is not None and lv and time.perf_counter() - lv > 1.5:
                break
            continue
        m, p = msg["method"], msg.get("params", {})
        if m.endswith("realtime/sdp") and not answered:
            await pc.setRemoteDescription(RTCSessionDescription(p["sdp"], "answer"))
            answered = True
            for _ in range(100):
                if pc.connectionState == "connected":
                    break
                await asyncio.sleep(0.1)
            if srv.verbose:
                print("  pc:", pc.connectionState)
            state["t0"] = time.perf_counter()
            if strategy == "S1":
                await call("thread/realtime/appendSpeech", {"threadId": tid, "text": text})
            else:
                await call("thread/realtime/appendText", {"threadId": tid, "text": text, "role": "user"})
        elif m.endswith("transcript/done") and p.get("role") == "assistant":
            transcript = (transcript + " " if transcript else "") + p["text"]
        elif m.endswith("realtime/error") or m.endswith("realtime/closed"):
            err = p.get("message") or p.get("reason")
            break
    await call("thread/realtime/stop", {"threadId": tid})
    await pc.close()
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / f"{fixture}_{strategy}_{n}.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    return {"fixture": fixture, "strategy": strategy, "n": n, "first_audio_s": state["first"],
            "audio_s": len(pcm) / 48000, "wer": wer(text, transcript or ""),
            "transcript": transcript, "error": err}


def main():
    args = sys.argv[1:]
    if args[:1] == ["--one"]:
        srv = AppServer(verbose=True)
        print(json.dumps(asyncio.run(run(srv, args[1], args[2], 0)), ensure_ascii=False, indent=1))
        return
    srv, rows = AppServer(verbose=False), []
    for strategy in ("S1", "S2"):
        for fixture in LANG:
            for n in range(3):
                r = asyncio.run(run(srv, fixture, strategy, n))
                rows.append(r)
                print(f"{strategy} {fixture:8} #{n} wer={r['wer']:.2f} first={r['first_audio_s']} err={r['error']}")
    (OUT / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
