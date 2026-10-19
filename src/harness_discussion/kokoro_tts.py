"""Kokoro, an open-weight neural voice that runs on this computer. Its model is downloaded once, on request."""
import hashlib
import logging
import os
import queue
import threading
import time
from pathlib import Path
from urllib.request import Request

from . import sentences, settings, updates
from .audio import NoAudioError, PcmPlayer
from .engines import _Threaded

log = logging.getLogger(__name__)
DIR = Path(settings.LOCAL_DIR) / "kokoro"
URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODEL, VOICES_FILE = "kokoro-v1.0.int8.onnx", "voices-v1.0.bin"
FILES = {MODEL: (92361271, "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"),
         VOICES_FILE: (28214398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d")}
LANGS = {"en-US": "en-us", "es-ES": "es", "fr-FR": "fr-fr"}  # Kokoro has no Hebrew, Arabic or Russian voice
OTHER_VOICES = {"es-ES": "ef_dora", "fr-FR": "ff_siwis"}  # the picker chooses the English voice
VOICES = tuple((v, f"{v[3:].capitalize()} ({'US' if v[0] == 'a' else 'UK'})") for v in (
    "af_heart af_alloy af_aoede af_bella af_jessica af_kore af_nicole af_nova af_river af_sarah af_sky "
    "am_adam am_echo am_eric am_fenrir am_liam am_michael am_onyx am_puck am_santa "
    "bf_alice bf_emma bf_isabella bf_lily bm_daniel bm_fable bm_george bm_lewis").split())
_download = None  # the thread fetching the model


def downloaded(directory=DIR):
    return all((directory / name).is_file() and (directory / name).stat().st_size == size
               for name, (size, _) in FILES.items())


def _verified(path, digest):
    sha = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest() == digest


def drop_corrupt(directory=DIR):
    """Deletes files whose SHA-256 no longer matches, so the row offers Download… again. Hashing ~120 MB is too
    slow for every status check, so this runs only after the model fails to load."""
    for name, (_, digest) in FILES.items():
        path = directory / name
        if path.is_file() and not _verified(path, digest):
            path.unlink(missing_ok=True)


def download(directory=DIR):
    """Fetches each missing file and keeps it only when its size and SHA-256 match."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, (size, digest) in FILES.items():
        path = directory / name
        if path.is_file() and path.stat().st_size == size and _verified(path, digest):
            continue
        part = path.with_name(name + ".part")
        try:
            sha, got, deadline = hashlib.sha256(), 0, time.monotonic() + 600
            request = Request(URL + name, headers={"User-Agent": "HarnessDiscussion"})
            with updates.urlopen(request, timeout=15) as reply, part.open("wb") as out:
                if not updates._trusted(reply.geturl()):
                    raise ValueError("Unexpected model download location")
                while chunk := reply.read(1024 * 1024):
                    got += len(chunk)
                    if got > size or time.monotonic() > deadline:
                        raise ValueError("Model download exceeded its size or time limit")
                    out.write(chunk)
                    sha.update(chunk)
            if got != size or sha.hexdigest() != digest:
                raise ValueError("Model verification failed")
            os.replace(part, path)
        finally:
            part.unlink(missing_ok=True)


def start_download():
    global _download
    if _download and _download.is_alive():
        return

    def run():
        try:
            download(DIR)
        except Exception as e:  # the row offers Download… again
            log.warning("kokoro download failed: %s", e)
    _download = threading.Thread(target=run, daemon=True)
    _download.start()


def status():
    try:
        import kokoro_onnx  # noqa: F401  a build without the runtime cannot read, downloaded or not
    except Exception:
        return "missing"
    if _download and _download.is_alive():
        return "downloading"
    return "ready" if downloaded(DIR) else "not_downloaded"


def self_test():
    """The built app bundles ONNX Runtime and espeak-ng with its data."""
    import onnxruntime  # noqa: F401
    from kokoro_onnx.tokenizer import Tokenizer
    if not Tokenizer().phonemize("test", "en-us"):
        raise RuntimeError("espeak-ng returned no phonemes")


class KokoroEngine(_Threaded):
    name, voices, default_voice = "Kokoro", VOICES, "af_heart"
    voice = None  # set by core; None reads with the default
    Player = PcmPlayer  # tests swap in one without a sound device

    def __init__(self):
        super().__init__()
        self._model = None  # loaded on the first read, then kept

    def status(self):
        return status()

    def _load(self):
        if self._model is None:
            from kokoro_onnx import Kokoro
            self._model = Kokoro(str(DIR / MODEL), str(DIR / VOICES_FILE))
        return self._model

    def _run(self, text, tag, stop, on_audio):
        if tag not in LANGS:
            raise NoAudioError(f"Kokoro: no voice for {tag}")
        voice = OTHER_VOICES.get(tag) or self.voice or self.default_voice
        try:
            import numpy as np
            model = self._load()
        except Exception as e:
            if downloaded(DIR):
                drop_corrupt(DIR)
            raise NoAudioError(f"Kokoro: {type(e).__name__}") from e
        pieces, speed = queue.Queue(), self.speed

        def synthesize():  # its own thread, so Stop ends playback without waiting for a sentence to render
            try:
                for sentence in sentences.split(text):
                    if stop.is_set():
                        return
                    try:
                        pieces.put(model.create(sentence, voice=voice, speed=speed, lang=LANGS[tag])[0])
                    except ValueError:
                        pass  # nothing to pronounce, such as a lone symbol
                pieces.put(None)
            except Exception as e:
                pieces.put(e)
        threading.Thread(target=synthesize, daemon=True).start()
        player = None
        try:
            while True:
                try:
                    samples = pieces.get(timeout=0.05)
                except queue.Empty:
                    if stop.is_set():
                        return
                    continue
                if samples is None or stop.is_set():
                    break
                if isinstance(samples, Exception):
                    if player is None:
                        raise NoAudioError(f"Kokoro: {type(samples).__name__}") from samples
                    raise samples  # speech already started: the chain must not restart it on another engine
                if player is None:
                    try:
                        player = self.Player(24000, 1, self.paused)
                    except Exception as e:
                        raise NoAudioError(f"Kokoro: {e}") from e
                    player.arm(on_audio)
                player.write((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
            if stop.is_set():
                return
            if player is None:
                raise NoAudioError("Kokoro: no audio")
            while player.pending and player.active and not stop.wait(0.05):
                pass
        finally:
            if player:
                player.close()
