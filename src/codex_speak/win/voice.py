"""The offline Windows voice (SAPI)."""
import math

import comtypes
import comtypes.client

from .. import lang
from ..audio import NoAudioError
from ..engines import _Threaded

ONECORE = r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices"  # Hebrew Asaf lives only here


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
