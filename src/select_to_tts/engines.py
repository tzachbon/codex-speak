"""Fallback engines (Edge neural, offline Windows) and the chain that tries engines in order."""
import contextlib
import logging
import math
import threading
import time

import comtypes
import comtypes.client
import edge_tts

from . import lang
from .audio import NoAudioError, PcmPlayer
from .edge_stream import EdgeStream

log = logging.getLogger(__name__)

ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"  # Hebrew Asaf lives only here


class _Threaded:
    """Runs a read on a worker thread: `_run(text, tag, stop, on_audio)`, or whatever `_start` is given. Runs never overlap."""
    speed = 1.0

    def __init__(self):
        self._stop, self._busy, self.paused = threading.Event(), threading.Lock(), threading.Event()

    def speak(self, text, lang_tag, on_done, on_audio=lambda: None):
        self._start(lambda stop: self._run(text, lang_tag or lang.detect(text), stop, on_audio), on_done)

    def _start(self, run, on_done, cleanup=lambda: None):
        paused = self.paused.is_set()
        self.stop()
        if paused:
            self.paused.set()
        self._stop = stop = threading.Event()

        def work():
            with self._busy:
                try:
                    if not stop.is_set():
                        run(stop)
                except Exception as e:
                    return on_done(e)
                finally:
                    cleanup()  # also when a newer read replaced this one before it started
            on_done(None)

        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self._stop.set()
        self.paused.clear()

    def pause(self):
        self.paused.set()

    def resume(self):
        self.paused.clear()

    def close(self):
        self.stop()


class EdgeEngine(_Threaded):
    name = "Edge"
    Player = PcmPlayer  # tests swap in one without a sound device

    def __init__(self):
        super().__init__()
        self._pre = None  # (request, stream) started before Play

    async def _source(self, text, voice, rate):
        stream = edge_tts.Communicate(text, voice, rate=rate).stream()
        async with contextlib.aclosing(stream):  # a stopped read closes the connection, not the garbage collector
            async for chunk in stream:
                if chunk["type"] == "audio":
                    yield chunk["data"]

    def _request(self, text, tag):
        voice = lang.LANGS.get(tag, lang.LANGS["en-US"])[1]
        return text, voice, f"{round((self.speed - 1) * 100):+d}%"

    def discard(self):
        """Drop a prefetch. Never stops a read in progress."""
        pre, self._pre = self._pre, None
        if pre:
            pre[1].cancel()

    def prepare(self, lang_tag, text=None):
        """Start the request before Play, so Play joins it. No text: just drop what was prepared."""
        self.discard()
        if text:
            request = self._request(text, lang_tag or lang.detect(text))
            self._pre = request, EdgeStream(self._source(*request))

    def speak(self, text, lang_tag, on_done, on_audio=lambda: None):
        tag = lang_tag or lang.detect(text)
        request, pre = self._request(text, tag), self._pre
        if pre and pre[0] == request and not pre[1].error:  # a prefetch that failed is not worth joining
            self._pre, stream = None, pre[1]  # claimed first: stop() in _start drops only a stale one
        else:
            self.discard()
            stream = EdgeStream(self._source(*request))  # starts now, not when the worker gets the lock
        self._start(lambda stop: self._play(stream, stop, on_audio), on_done, stream.cancel)

    def stop(self):
        self.discard()
        super().stop()

    def _play(self, stream, stop, on_audio):
        player = None
        try:
            chunks = stream.read(stop)
            while True:
                starved, t = player is not None and not player.pending, time.monotonic()
                try:
                    pcm = next(chunks, None)
                except Exception as e:
                    if player is None:
                        raise NoAudioError(f"Edge: {e}") from e
                    raise  # speech already started: the chain must not restart it on another engine
                if pcm is None:
                    break
                if starved and time.monotonic() - t > 0.3:
                    log.info("edge stream stalled %.1fs after first audio", time.monotonic() - t)
                if player is None:
                    try:
                        player = self.Player(24000, 1, self.paused)
                    except Exception as e:
                        raise NoAudioError(f"Edge: {e}") from e
                    player.arm(on_audio)
                player.write(pcm)
            if stop.is_set():
                return
            if player is None:
                raise NoAudioError("Edge: no audio")
            while player.pending and player.active and not stop.wait(0.05):
                pass  # the queue still holds speech after the download ends
        finally:
            stream.cancel()
            if player:
                player.close()


def sapi_rate(speed):
    """SAPI rate runs -10..10, where +10 is about 3x and -10 about 1/3x."""
    return max(-10, min(10, round(10 * math.log(speed, 3))))


class SapiEngine(_Threaded):
    name = "Windows"

    def _run(self, text, tag, stop, on_audio):
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
        while self.paused.is_set():
            if stop.wait(0.05):
                return
        if stop.is_set():
            return
        voice.Speak(text, 1)  # SVSFlagsAsync
        on_audio()
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
        self.engines, self.only, self.last, self.prefetch = engines, None, None, False
        self._active, self._gen, self._paused = None, 0, False

    def order(self):
        if self.only:
            return [e for e in self.engines if e.name == self.only] or self.engines
        # Auto skips engines that cannot reach the chosen speed (Codex cannot read faster)
        return [e for e in self.engines if e.speed <= getattr(e, "max_speed", e.speed)] or self.engines

    def prepare(self, lang_tag, text=None):
        first = self.order()[0]
        for e in self.engines:
            if e is not first and hasattr(e, "discard"):
                e.discard()  # a speed or engine change can hand the read to another engine
        if hasattr(first, "prepare"):
            first.prepare(lang_tag, text if self.prefetch else None)

    def speak(self, text, lang_tag, on_done, on_audio=lambda: None):
        self._gen += 1
        self._paused = False
        gen, order = self._gen, self.order()
        for e in self.engines:
            if e is not order[0]:
                e.stop()

        def attempt(i):
            engine = self._active = order[i]
            if hasattr(engine, "paused"):
                engine.paused.set() if self._paused else engine.paused.clear()

            def done(err):
                if gen != self._gen:
                    return  # superseded by a newer speak()
                if isinstance(err, NoAudioError) and i + 1 < len(order):
                    return attempt(i + 1)
                self.last = engine.name
                on_done(err)

            engine.speak(text, lang_tag, done, lambda: gen == self._gen and on_audio())
            if gen == self._gen and self._paused:
                engine.pause()  # a pause made before a fallback carries over to the next engine

        attempt(0)

    def stop(self):
        self._gen += 1
        for e in self.engines:
            e.stop()

    def pause(self):
        self._paused = True
        if self._active:
            self._active.pause()

    def resume(self):
        self._paused = False
        if self._active:
            self._active.resume()

    def close(self):
        for e in self.engines:
            e.close()
