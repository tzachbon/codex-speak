"""The offline macOS voice (AVSpeechSynthesizer). Speech stays on this Mac."""
import time

from AVFoundation import (AVSpeechBoundaryImmediate, AVSpeechSynthesisVoice, AVSpeechSynthesizer,
                          AVSpeechUtterance, AVSpeechUtteranceDefaultSpeechRate,
                          AVSpeechUtteranceMaximumSpeechRate, AVSpeechUtteranceMinimumSpeechRate)

from ..audio import NoAudioError
from ..engines import _Threaded


def av_rate(speed):
    """AVSpeech rates run 0..1 with 0.5 as normal speech; slower and faster scale separately."""
    normal = AVSpeechUtteranceDefaultSpeechRate
    rate = normal * speed if speed <= 1 else normal + (AVSpeechUtteranceMaximumSpeechRate - normal) * (speed - 1)
    return min(max(rate, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)


class MacVoiceEngine(_Threaded):
    name = "macOS"

    def _run(self, text, tag, stop, on_audio):
        voice = AVSpeechSynthesisVoice.voiceWithLanguage_(tag)
        if voice is None:
            raise NoAudioError(f"macOS: no installed voice for {tag}")
        synth = AVSpeechSynthesizer.alloc().init()
        utterance = AVSpeechUtterance.speechUtteranceWithString_(text)
        utterance.setVoice_(voice)
        utterance.setRate_(av_rate(self.speed))
        while self.paused.is_set():
            if stop.wait(0.05):
                return
        if stop.is_set():
            return
        synth.speakUtterance_(utterance)
        deadline = time.monotonic() + 2
        while not synth.isSpeaking():
            if stop.wait(0.02):
                synth.stopSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
                return
            if time.monotonic() > deadline:
                synth.stopSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
                raise NoAudioError("macOS: the voice did not start")
        on_audio()
        held = False
        while synth.isSpeaking() or synth.isPaused():
            if stop.wait(0.05):
                synth.stopSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
                return
            if self.paused.is_set() != held:
                held = self.paused.is_set()
                if held:
                    synth.pauseSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
                else:
                    synth.continueSpeaking()
