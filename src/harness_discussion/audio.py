"""Speaker output: streamed 16-bit PCM (Codex and Edge)."""
import array
import threading
import time
from fractions import Fraction

import av
import sounddevice as sd

VOICED = 500  # int16 peak that counts as speech rather than line noise
# Codex sends speech a few percent slower than real time, so a fixed head start drains mid-speech.
# The player keeps JITTER seconds queued and tops it up by lengthening pauses, where it isn't heard.
JITTER = 0.25
QUIET = 100  # int16 peak of a 20 ms block that is a pause; quiet consonants peak higher


class NoAudioError(RuntimeError):
    """An engine failed before producing any speech, so the next engine may take over."""


def peak(pcm: bytes) -> int:
    a = array.array("h", pcm)
    return max(max(a), -min(a)) if a else 0


class Stretcher:
    """Plays mono 16-bit PCM faster or slower at the same pitch (ffmpeg atempo via PyAV)."""

    def __init__(self, speed: float, rate: int = 24000):
        self._rate, self._pts, self._graph = rate, 0, None
        if speed != 1:
            g = self._graph = av.filter.Graph()
            src = g.add_abuffer(format="s16", sample_rate=rate, layout="mono",
                                time_base=Fraction(1, rate))
            tempo, sink = g.add("atempo", str(speed)), g.add("abuffersink")
            src.link_to(tempo)
            tempo.link_to(sink)
            g.configure()

    def __call__(self, pcm: bytes) -> bytes:
        if not self._graph or not pcm:
            return pcm
        frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
        frame.sample_rate, frame.time_base, frame.pts = self._rate, Fraction(1, self._rate), self._pts
        frame.planes[0].update(pcm[: frame.samples * 2])
        self._pts += frame.samples
        self._graph.push(frame)
        out = bytearray()
        while True:
            try:
                f = self._graph.pull()
            except (BlockingIOError, EOFError):
                return bytes(out)
            out += bytes(f.planes[0])[: f.samples * 2]


class PcmPlayer:
    _hold, _holding, _last_write = 0, False, 0.0  # no cushion for players built without a sound device

    def __init__(self, rate: int = 24000, channels: int = 1, paused: threading.Event | None = None):
        self._buf, self._lock, self._width = bytearray(), threading.Lock(), 2 * channels
        self._hold, self._holding = int(rate * JITTER) * self._width, True
        self._paused = paused or threading.Event()  # set: play silence and keep the queue
        self._on_audio = None
        self._output_pending = False
        # 20 ms blocks: left to choose, CoreAudio calls back every 15 samples and any stall is a gap
        self._stream = sd.RawOutputStream(samplerate=rate, channels=channels, dtype="int16",
                                          blocksize=rate // 50, callback=self._fill)
        self._stream.start()

    def _fill(self, out, frames, _time, _status):
        n = frames * self._width
        if self._paused.is_set():
            out[:] = bytes(n)
            return
        with self._lock:
            more = not self._last_write or time.monotonic() - self._last_write < JITTER  # else play the tail
            if len(self._buf) >= self._hold or not more:
                self._holding = False
            elif not self._buf:
                self._holding = True  # ran dry: wait for a full cushion rather than play each late packet
            if self._holding or (len(self._buf) < self._hold and more and peak(self._buf[:n]) < QUIET):
                chunk = b""
            else:
                chunk = bytes(self._buf[:n])
                del self._buf[:n]
                self._holding = len(chunk) < n
            self._output_pending = bool(chunk)  # drain cannot complete ahead of the start notification
            on_audio = self._on_audio if peak(chunk) > VOICED else None
            if on_audio:
                self._on_audio = None
        try:
            out[: len(chunk)] = chunk
            out[len(chunk):] = bytes(n - len(chunk))
            if on_audio:
                on_audio()
        finally:
            self._output_pending = False

    def arm(self, on_audio):
        """Notify once when voiced PCM reaches unpaused output, never merely on receipt."""
        with self._lock:
            self._on_audio = on_audio

    def write(self, pcm: bytes) -> None:
        with self._lock:
            self._buf += pcm
            self._last_write = time.monotonic()

    @property
    def pending(self) -> bool:
        return bool(self._buf) or self._output_pending

    @property
    def active(self) -> bool:
        return self._stream.active

    def close(self) -> None:
        with self._lock:
            self._buf.clear()
            self._on_audio = None
        self._stream.abort()
        self._stream.close()
