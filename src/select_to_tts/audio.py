"""Speaker output: streamed 16-bit PCM (Codex) and MP3 files (Edge)."""
import array
import ctypes
import threading
import time

import sounddevice as sd


class NoAudioError(RuntimeError):
    """An engine failed before producing any speech, so the next engine may take over."""


def peak(pcm: bytes) -> int:
    a = array.array("h", pcm)
    return max(max(a), -min(a)) if a else 0


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

    def close(self, drain: bool = True) -> None:
        deadline = time.monotonic() + 5
        while drain and self._buf and time.monotonic() < deadline:
            time.sleep(0.05)
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
