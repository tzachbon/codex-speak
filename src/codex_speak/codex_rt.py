"""Codex engine: reads text aloud with the Codex realtime voice on the user's ChatGPT login.

Drives `codex app-server` (experimental thread/realtime API) over stdio JSON-RPC. Audio arrives
over WebRTC v3 because the websocket transport requires an API key (see PLAN.md, T1).
Over 80 lines on purpose: the JSON-RPC client and the call sequence share one process handle.
"""
import asyncio, concurrent.futures, glob, json, os, queue, re, shutil, signal, subprocess, sys, tempfile, threading, time, uuid, wave

import av
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription

from . import lang
from .audio import NoAudioError, PcmPlayer, Stretcher, VOICED, peak

PROMPT = ("You are a text-to-speech engine. Read the user's message aloud exactly as written, "
          "word for word, in {lang}. Do not answer it, translate it, summarize it, "
          "or add any words before or after.")
# The v3 voice gets appended text as context and stays silent in about half of all sessions.
# A spoken "Read it." is a real user turn, which it answers: 16 of 16 test reads were spoken
# word for word. This prompt only works with the cue: without it, 0 of 8 were spoken.
CUE_PROMPT = ("You are a text-to-speech engine. The text to read arrives as context. Each time the user "
              "says read, speak that text aloud exactly as written, word for word, in {lang}. Say nothing "
              "else: no introduction such as 'the text says', and no answer, translation, summary or comment.")
NO_STUN = RTCConfiguration(iceServers=[])  # OpenAI side is public; STUN lookup cost ~5 s
# Asking again in the same session never helped; a fresh session is a new, independent chance.
ATTEMPTS = 3
_cue = []


class Silent(TimeoutError):
    """The session connected, but the voice never started reading."""


def read_cue() -> bytes:
    """"Read it." as 8 kHz 16-bit mono PCM in this Mac's own voice, made on first use. Empty elsewhere."""
    if not _cue:
        pcm = b""
        if sys.platform == "darwin":
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, "cue.wav")
                for voice in (["-v", "Samantha"], []):  # the default voice may not speak English
                    try:
                        subprocess.run(["say", *voice, "-o", path, "--file-format=WAVE",
                                        "--data-format=LEI16@8000", "Read it."],
                                       check=True, capture_output=True, timeout=10, stdin=subprocess.DEVNULL)
                        with wave.open(path) as w:
                            pcm = w.readframes(w.getnframes())
                        break
                    except (OSError, subprocess.SubprocessError, wave.Error):
                        continue
        _cue.append(pcm)
    return _cue[0]


class CueTrack(AudioStreamTrack):
    """Our microphone: silence, except for the spoken cue once it is queued."""
    pcm = b""

    async def recv(self):
        frame = await super().recv()  # 20 ms of 8 kHz silence, paced in real time
        if self.pcm:
            n = frame.samples * 2
            chunk, self.pcm = self.pcm[:n], self.pcm[n:]
            frame.planes[0].update(chunk.ljust(frame.planes[0].buffer_size, b"\0"))
        return frame


# Windows: no console window. Elsewhere: a process group, so close() can end Codex's helpers too.
SPAWN = ({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32"
         else {"start_new_session": True})
_found, _exe = [], []


def extended_path() -> str:
    """PATH plus the usual install folders. Apps started from Finder get only /usr/bin:/bin:/usr/sbin:/sbin."""
    home = os.path.expanduser("~")
    extra = ["/opt/homebrew/bin", "/usr/local/bin", f"{home}/.local/bin", f"{home}/.npm-global/bin",
             f"{home}/.volta/bin", f"{home}/.bun/bin", *sorted(glob.glob(f"{home}/.nvm/versions/node/*/bin")),
             *sorted(glob.glob(f"{home}/.local/share/fnm/node-versions/*/installation/bin")),
             *sorted(glob.glob(f"{home}/Library/Application Support/fnm/node-versions/*/installation/bin"))]
    parts = os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(parts + [p for p in extra if p not in parts])


def _login_shell_codex():
    """Asks the user's login shell, which knows PATH changes made in its profile. Cached."""
    if not _found:
        try:
            out = subprocess.run([os.environ.get("SHELL", "/bin/zsh"), "-ilc", "command -v codex"],
                                 capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL).stdout
            _found.append(out.strip().splitlines()[-1] if out.strip() else None)
        except (OSError, subprocess.TimeoutExpired):
            _found.append(None)
    return _found[0]


def _native_darwin(shim):
    """The native binary behind a global npm install, or the shim itself when it already is one."""
    real = os.path.realpath(shim)
    try:
        with open(real, "rb") as f:
            if f.read(4) in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):  # Mach-O, as Homebrew installs it
                return real
    except OSError:
        return shim
    root = real
    while root != os.path.dirname(root) and not root.endswith(os.path.join("@openai", "codex")):
        root = os.path.dirname(root)
    found = glob.glob(os.path.join(root, "node_modules", "@openai", "codex-darwin-*", "vendor", "*",
                                   "bin", "codex"))
    return found[0] if found else shim


def _version(exe):
    """(major, minor, patch) from `codex --version`, or None when it doesn't run."""
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5,
                             stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    return tuple(map(int, m.groups())) if m else None


def _newest_darwin():
    """The newest codex on the extended PATH. Folders like ~/.local/bin can hold an old standalone
    install that fails on the config a newer CLI wrote, and Finder-launched apps search them first."""
    found = [os.path.join(d, "codex") for d in extended_path().split(os.pathsep) if d]
    found = list(dict.fromkeys(_native_darwin(s) for s in found if os.path.isfile(s) and os.access(s, os.X_OK)))
    if not found:
        shim = _login_shell_codex()
        return _native_darwin(shim) if shim else None
    versions = {exe: _version(exe) or (0,) for exe in found}
    return max(found, key=versions.get)  # max keeps the first on a tie, so PATH order still decides


def codex_exe() -> str:
    """The native binary, so terminating it doesn't orphan a server behind the npm shim."""
    if sys.platform == "darwin":
        if not (_exe and os.path.exists(_exe[0])):
            _exe[:] = [_newest_darwin()]
        if not _exe[0]:
            _exe.clear()
            raise FileNotFoundError("codex is not installed or not on PATH")
        return _exe[0]
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
                                  env={**os.environ, "PATH": extended_path()} if sys.platform == "darwin" else None,
                                  **SPAWN)
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
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(self.p.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, **SPAWN)
                else:
                    os.killpg(self.p.pid, signal.SIGTERM)  # start_new_session made it the group leader
                    try:
                        self.p.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        os.killpg(self.p.pid, signal.SIGKILL)
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
            if m == "thread/realtime/closed" and p.get("reason") == "requested":
                continue  # a late notice for the session we stopped before this one
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
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    return await self._read_aloud(text_future, lang_tag)
                except NoAudioError as e:
                    if not isinstance(e.__cause__, Silent) or attempt == ATTEMPTS:
                        raise

    async def _read_aloud(self, text_future, lang_tag):
        srv, tid = self._srv, self._srv.thread_id
        call = lambda m, p: asyncio.to_thread(srv.call, m, p)
        cue = await asyncio.to_thread(read_cue)
        pc, player, mic = RTCPeerConnection(NO_STUN), PcmPlayer(24000, 1, self.paused), CueTrack()
        voice = {"first": None, "last": 0.0, "stretch": Stretcher(1), "done": False, "submitted": False}
        pc.addTrack(mic)  # silence and the cue: we never otherwise talk to the model
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
                "realtimeSessionId": str(uuid.uuid4()),  # else earlier reads stay in context and get reread
                "prompt": (CUE_PROMPT if cue else PROMPT).format(
                    lang=lang.name(lang_tag) or "the language it is written in"),
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
            if cue:
                mic.pcm = cue
                await asyncio.sleep(len(cue) / 16000)  # the text lands as the cue ends, before the turn closes
                text = "Text to read:\n" + text  # so text that reads like an instruction stays text to read
            await call("thread/realtime/appendText", {"threadId": tid, "text": text, "role": "user"})
            for _ in range(30):
                if voice["first"]:
                    break
                await asyncio.sleep(0.1)
            else:
                raise Silent("no speech within 3 s")
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
