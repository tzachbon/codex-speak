"""Speaker output: streamed 16-bit PCM (Codex) and MP3 files (Edge)."""
import array
import ctypes
import threading
import time
from fractions import Fraction

import av
import sounddevice as sd


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
    def __init__(self, rate: int = 24000, channels: int = 1):
        self._buf, self._lock, self._width = bytearray(), threading.Lock(), 2 * channels
        self._stream = sd.RawOutputStream(samplerate=rate, channels=channels, dtype="int16",
                                          callback=self._fill)
        self._stream.start()

    def _fill(self, out, frames, _time, _status):
        n = frames * self._width
        with self._lock:
            chunk = bytes(self._buf[:n])
            del self._buf[:n]
        out[: len(chunk)] = chunk
        out[len(chunk):] = bytes(n - len(chunk))

    def write(self, pcm: bytes) -> None:
        with self._lock:
            self._buf += pcm

    @property
    def pending(self) -> bool:
        return bool(self._buf)

    def close(self) -> None:
        with self._lock:
            self._buf.clear()
        self._stream.abort()
        self._stream.close()


def _mci(cmd: str) -> str:
    out = ctypes.create_unicode_buffer(128)
    err = ctypes.windll.winmm.mciSendStringW(cmd, out, 128, None)
    if err:
        raise RuntimeError(f"MCI error {err}: {cmd}")
    return out.value


def play_mp3(path: str, stop: threading.Event) -> None:
    """Blocks until the file finishes or `stop` is set. All MCI calls stay on this thread."""
    alias = f"tts{threading.get_ident()}"
    _mci(f'open "{path}" type mpegvideo alias {alias}')
    try:
        _mci(f"play {alias}")
        while not stop.wait(0.05) and _mci(f"status {alias} mode") == "playing":
            pass
    finally:
        _mci(f"close {alias}")
