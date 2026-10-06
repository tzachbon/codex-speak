"""Fallback engines (Edge neural, offline Windows) and the chain that tries engines in order."""
import asyncio
import math
import os
import tempfile
import threading

import comtypes
import comtypes.client
import edge_tts

from . import lang, settings
from .audio import NoAudioError, play_mp3

ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"  # Hebrew Asaf lives only here


class _Threaded:
    """Runs `_run(text, tag, stop)` on a worker thread. Runs never overlap."""
    speed = 1.0

    def __init__(self):
        self._stop, self._busy, self.paused = threading.Event(), threading.Lock(), threading.Event()

    def speak(self, text, lang_tag, on_done):
        self.stop()
        self.paused.clear()
        self._stop = stop = threading.Event()

        def work():
            with self._busy:
                try:
                    if not stop.is_set():
                        self._run(text, lang_tag or lang.detect(text), stop)
                except Exception as e:
                    return on_done(e)
            on_done(None)

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self._stop.set()

    def pause(self):
        self.paused.set()

    def resume(self):
        self.paused.clear()

    def close(self):
        self.stop()


class EdgeEngine(_Threaded):
    name = "Edge"

    def _run(self, text, tag, stop):
        voice = lang.LANGS.get(tag, lang.LANGS["en-US"])[1]
        os.makedirs(settings.TEMP_DIR, exist_ok=True)
        fd, path = tempfile.mkstemp(suffix=".mp3", dir=settings.TEMP_DIR)
        os.close(fd)
        try:
            try:
                rate = f"{round((self.speed - 1) * 100):+d}%"
                asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(path))
            except Exception as e:
                raise NoAudioError(f"Edge: {e}") from e
            # ponytail: buffers the whole MP3 before playing, stream it if long selections lag
            play_mp3(path, stop, self.paused)
        finally:
            os.remove(path)


def sapi_rate(speed):
    """SAPI rate runs -10..10, where +10 is about 3x and -10 about 1/3x."""
    return max(-10, min(10, round(10 * math.log(speed, 3))))


class SapiEngine(_Threaded):
    name = "Windows"

    def _run(self, text, tag, stop):
        prefix = lang.LANGS.get(tag, (None, None, None))[2]
        comtypes.CoInitialize()
        cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
        cat.SetId(ONECORE, False)
        tokens = cat.EnumerateTokens()
        match = [tokens.Item(i) for i in range(tokens.Count)
                 if prefix and tokens.Item(i).GetDescription().startswith(prefix)]
        if not match:
            raise NoAudioError(f"Windows: no installed voice for {tag}")
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
        voice.Voice = match[0]
        voice.Rate = sapi_rate(self.speed)
        voice.Speak(text, 1)  # SVSFlagsAsync
        held = False
        while not voice.WaitUntilDone(50):
            if stop.is_set():
                if held:
                    voice.Resume()  # a paused voice would not purge
                voice.Speak("", 3)  # async | purge: silence now
                return
            if self.paused.is_set() != held:  # COM calls stay on this thread
                held = self.paused.is_set()
                voice.Pause() if held else voice.Resume()


class Chain:
    """Tries engines in order, moving on only when one fails before producing any speech."""

    def __init__(self, engines):
        self.engines, self.only, self.last = engines, None, None
        self._active, self._gen = None, 0

    def order(self):
        if self.only:
            return [e for e in self.engines if e.name == self.only] or self.engines
        # Auto skips engines that cannot reach the chosen speed (Codex cannot read faster)
        return [e for e in self.engines if e.speed <= getattr(e, "max_speed", e.speed)] or self.engines

    def prepare(self, lang_tag):
        first = self.order()[0]
        if hasattr(first, "prepare"):
            first.prepare(lang_tag)

    def speak(self, text, lang_tag, on_done):
        self._gen += 1
        gen, order = self._gen, self.order()
        for e in self.engines:
            if e is not order[0]:
                e.stop()

        def attempt(i):
            engine = self._active = order[i]

            def done(err):
                if gen != self._gen:
                    return  # superseded by a newer speak()
                if isinstance(err, NoAudioError) and i + 1 < len(order):
                    return attempt(i + 1)
                self.last = engine.name
                on_done(err)

            engine.speak(text, lang_tag, done)

        attempt(0)

    def stop(self):
        self._gen += 1
        for e in self.engines:
            e.stop()

    def pause(self):
        if self._active:
            self._active.pause()

    def resume(self):
        if self._active:
            self._active.resume()

    def close(self):
        for e in self.engines:
            e.close()
