"""Codex engine: reads text aloud with the Codex realtime voice on the user's ChatGPT login.

Drives `codex app-server` (experimental thread/realtime API) over stdio JSON-RPC. Audio arrives
over WebRTC v3 because the websocket transport requires an API key (see PLAN.md, T1).
Over 80 lines on purpose: the JSON-RPC client and the call sequence share one process handle.
"""
import asyncio, glob, json, os, queue, shutil, subprocess, threading, time

import av
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from . import lang
from .audio import NoAudioError, PcmPlayer, peak

PROMPT = ("You are a text-to-speech engine. Read the user's message aloud exactly as written, "
          "word for word, in {lang}. Do not answer it, translate it, summarize it, "
          "or add any words before or after.")
VOICED = 500  # int16 peak that counts as speech rather than line noise
NO_STUN = RTCConfiguration(iceServers=[])  # OpenAI side is public; STUN lookup cost ~5 s


def codex_exe() -> str:
    """The native binary, so terminating it doesn't orphan a server behind the npm shim."""
    shim = shutil.which("codex")
    if not shim:
        raise FileNotFoundError("codex is not on PATH")
    found = glob.glob(os.path.join(os.path.dirname(shim), "node_modules", "@openai", "codex",
                                   "node_modules", "@openai", "codex-win32-*", "vendor", "*",
                                   "bin", "codex.exe"))
    return found[0] if found else shim


class AppServer:
    def __init__(self):
        self.p = subprocess.Popen([codex_exe(), "app-server"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  encoding="utf-8", bufsize=1,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
        self.events, self._pending, self._next, self._lock = queue.Queue(), {}, 0, threading.Lock()
        threading.Thread(target=self._read, daemon=True).start()
        self.call("initialize", {"clientInfo": {"name": "select-to-tts", "version": "0.1.0"},
                                 "capabilities": {"experimentalApi": True}})
        self._send({"method": "initialized"})
        self.thread_id = self.call("thread/start", {"ephemeral": True})["thread"]["id"]

    @property
    def alive(self) -> bool:
        return self.p.poll() is None

    def _send(self, msg):
        with self._lock:
            self.p.stdin.write(json.dumps(msg) + "\n")
            self.p.stdin.flush()

    def _read(self):
        for line in self.p.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "id" in msg and "method" in msg:  # server request (approval etc.): refuse
                self._send({"id": msg["id"], "error": {"code": -32601, "message": "unsupported"}})
            elif msg.get("id") in self._pending:
                self._pending.pop(msg["id"]).put(msg)
            else:
                self.events.put(msg)
        for box in list(self._pending.values()):
            box.put({"error": "codex app-server exited"})

    def call(self, method, params, timeout=20):
        with self._lock:
            self._next += 1
            box = self._pending[self._next] = queue.Queue()
        self._send({"id": self._next, "method": method, "params": params})
        msg = box.get(timeout=timeout)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg["result"]

    def close(self):
        self.p.kill()


class CodexEngine:
    name = "Codex"

    def __init__(self):
        self._srv, self._job = None, None
        self._busy = asyncio.Lock()  # a cancelled read must finish cleanup before the next starts
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    def speak(self, text, lang_tag, on_done):
        self.stop()
        self._job = asyncio.run_coroutine_threadsafe(self._speak(text, lang_tag), self._loop)
        self._job.add_done_callback(
            lambda f: on_done(None if f.cancelled() else f.exception()))

    def stop(self):
        if self._job and not self._job.done():
            self._job.cancel()

    def close(self):
        self.stop()
        if self._srv:
            self._srv.close()

    async def _next_event(self, srv, want, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not srv.alive:
                raise RuntimeError("codex app-server exited")
            try:
                msg = await asyncio.to_thread(srv.events.get, True, 0.2)
            except queue.Empty:
                continue
            m, p = msg["method"], msg.get("params", {})
            if m in ("thread/realtime/error", "thread/realtime/closed"):
                raise RuntimeError(p.get("message") or f"realtime closed: {p.get('reason')}")
            if m == want:
                return p
        raise TimeoutError(want)

    async def _speak(self, text, lang_tag):
        async with self._busy:
            await self._read_aloud(text, lang_tag)

    async def _read_aloud(self, text, lang_tag):
        if not (self._srv and self._srv.alive):
            self._srv = await asyncio.to_thread(AppServer)
        srv, tid = self._srv, self._srv.thread_id
        call = lambda m, p: asyncio.to_thread(srv.call, m, p)
        pc, player, voice = RTCPeerConnection(NO_STUN), PcmPlayer(24000, 1), {"first": None, "last": 0.0}
        pc.addTrack(AudioStreamTrack())  # silence: we never talk to the model
        pc.createDataChannel("oai-events")
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
                        pcm = bytes(f.planes[0])[: f.samples * 2]
                        player.write(pcm)
                        if peak(pcm) > VOICED:
                            voice["first"] = voice["first"] or time.monotonic()
                            voice["last"] = time.monotonic()
            asyncio.ensure_future(pump())

        ok = False
        try:
            while not srv.events.empty():
                srv.events.get_nowait()
            await pc.setLocalDescription(await pc.createOffer())
            await call("thread/realtime/start", {
                "threadId": tid, "outputModality": "audio", "version": "v3",
                "includeStartupContext": False, "clientManagedHandoffs": True,
                "prompt": PROMPT.format(lang=lang.name(lang_tag) or "the language it is written in"),
                "transport": {"type": "webrtc", "sdp": pc.localDescription.sdp}})
            answer = await self._next_event(srv, "thread/realtime/sdp", 10)
            await pc.setRemoteDescription(RTCSessionDescription(answer["sdp"], "answer"))
            for _ in range(100):
                if pc.connectionState == "connected":
                    break
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("WebRTC did not connect")
            await call("thread/realtime/appendText", {"threadId": tid, "text": text, "role": "user"})
            for _ in range(50):
                if voice["first"]:
                    break
                await asyncio.sleep(0.1)
            else:
                raise TimeoutError("no speech within 5 s")
            while True:
                p = await self._next_event(srv, "thread/realtime/transcript/done", 300)
                if p.get("role") == "assistant":
                    break
            while time.monotonic() - voice["last"] < 1.5:
                await asyncio.sleep(0.1)
            ok = True
        except Exception as e:
            if not voice["first"]:
                raise NoAudioError(f"Codex: {e}") from e
            raise
        finally:
            await pc.close()
            player.close(drain=ok)
            if srv.alive:
                try:
                    await call("thread/realtime/stop", {"threadId": tid})
                except Exception:
                    pass  # session may already be closed


if __name__ == "__main__":  # manual check: uv run python -m select_to_tts.codex_rt "text" [he-IL] [stop_after_s]
    import sys
    done = threading.Event()
    engine = CodexEngine()
    t0 = time.monotonic()
    engine.speak(sys.argv[1], (sys.argv[2:3] or [None])[0],
                 lambda e: (print(f"done after {time.monotonic() - t0:.1f}s, error={e!r}"), done.set()))
    if len(sys.argv) > 3:
        time.sleep(float(sys.argv[3]))
        engine.stop()
    done.wait()
    engine.close()
