"""Codex engine: reads text aloud with the Codex realtime voice on the user's ChatGPT login.

Drives `codex app-server` (experimental thread/realtime API) over stdio JSON-RPC. Audio arrives
over WebRTC v3 because the websocket transport requires an API key (see PLAN.md, T1).
Over 80 lines on purpose: the JSON-RPC client and the call sequence share one process handle.
"""
import asyncio, concurrent.futures, glob, json, os, queue, shutil, subprocess, threading, time

import av
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from . import lang
from .audio import NoAudioError, PcmPlayer, Stretcher, VOICED, peak

PROMPT = ("You are a text-to-speech engine. Read the user's message aloud exactly as written, "
          "word for word, in {lang}. Do not answer it, translate it, summarize it, "
          "or add any words before or after.")
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
        try:
            self.events, self._pending, self._next, self._lock = queue.Queue(), {}, 0, threading.Lock()
            self._reader = threading.Thread(target=self._read, daemon=True)
            self._reader.start()
            self.call("initialize", {"clientInfo": {"name": "codex-speak", "version": "0.1.0"},
                                     "capabilities": {"experimentalApi": True}})
            self._send({"method": "initialized"})
            self.thread_id = self.call("thread/start", {"ephemeral": True})["thread"]["id"]
        except BaseException:
            self.close()
            raise

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
        if self.alive:
            # Codex helpers can inherit stdout. End our process tree so the reader reaches EOF.
            try:
                subprocess.run(["taskkill", "/PID", str(self.p.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            if self.alive:
                self.p.kill()
        self.p.wait(timeout=5)
        reader = getattr(self, "_reader", None)
        if reader is not None and reader.ident is not None:
            reader.join(timeout=5)
        self.p.stdin.close()
        if reader is None or not reader.is_alive():
            self.p.stdout.close()


class CodexEngine:
    # WebRTC delivers speech in real time, so it can be stretched slower but never played faster
    name, speed, max_speed = "Codex", 1.0, 1.0

    def __init__(self):
        self._srv, self._job, self._text, self._tag = None, None, None, None
        self.paused = threading.Event()
        self._busy = asyncio.Lock()  # a cancelled read must finish cleanup before the next starts
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()

    def prepare(self, lang_tag, text=None):  # the text stays on this machine until Play
        """Connect ahead of Play (when the popup appears) so Play only sends text, saving ~1.3 s."""
        self.stop()
        self._tag, self._text = lang_tag, concurrent.futures.Future()
        self._job = asyncio.run_coroutine_threadsafe(self._speak(self._text, lang_tag), self._loop)

    def speak(self, text, lang_tag, on_done, on_audio=lambda: None):
        paused = self.paused.is_set()
        waiting = self._job and not self._job.done() and not self._text.done()
        if not (waiting and self._tag == lang_tag):
            self.prepare(lang_tag)
        self.paused.set() if paused else self.paused.clear()
        self._text.set_result((text, on_audio))
        self._job.add_done_callback(
            lambda f: on_done(None if f.cancelled() else f.exception()))

    def stop(self):
        self.paused.clear()  # else the next prepared session queues its warm-up silence
        if self._job and not self._job.done():
            self._job.cancel()

    def pause(self):
        self.paused.set()  # the model keeps streaming into the queue, which plays on resume

    def resume(self):
        self.paused.clear()

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

    async def _speak(self, text_future, lang_tag):
        async with self._busy:
            try:
                if not (self._srv and self._srv.alive):
                    self._srv = await asyncio.to_thread(AppServer)
            except Exception as e:
                raise NoAudioError(f"Codex: {e}") from e
            await self._read_aloud(text_future, lang_tag)

    async def _read_aloud(self, text_future, lang_tag):
        srv, tid = self._srv, self._srv.thread_id
        call = lambda m, p: asyncio.to_thread(srv.call, m, p)
        pc, player = RTCPeerConnection(NO_STUN), PcmPlayer(24000, 1, self.paused)
        voice = {"first": None, "last": 0.0, "stretch": Stretcher(1), "done": False, "submitted": False}
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
                    if voice["done"]:
                        continue  # the track keeps sending silence; don't queue it behind slowed speech
                    for f in resampler.resample(frame):
                        pcm = voice["stretch"](bytes(f.planes[0])[: f.samples * 2])
                        player.write(pcm)
                        if peak(pcm) > VOICED:
                            if voice["submitted"]:
                                voice["first"] = voice["first"] or time.monotonic()
                                voice["last"] = time.monotonic()
            asyncio.ensure_future(pump())

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
            text, on_audio = await asyncio.wait_for(asyncio.wrap_future(text_future), 30)
            voice["stretch"] = Stretcher(min(self.speed, self.max_speed))  # read at Play: settings apply
            player.arm(on_audio)
            voice["submitted"] = True
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
            voice["done"] = True
            while player.pending and player.active:
                await asyncio.sleep(0.05)  # slowed speech is still queued after the model finishes
        except Exception as e:
            if not voice["first"]:
                raise NoAudioError(f"Codex: {e}") from e
            raise
        finally:
            voice["done"] = True
            player.close()  # silence first: the WebRTC teardown below can be slow
            await pc.close()
            if srv.alive:
                try:
                    await call("thread/realtime/stop", {"threadId": tid})
                except Exception:
                    pass  # session may already be closed


if __name__ == "__main__":  # manual check: uv run python -m codex_speak.codex_rt "text" [he-IL] [stop_after_s]
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
