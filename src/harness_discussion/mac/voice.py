"""The offline macOS voice (AVSpeechSynthesizer). Speech stays on this Mac."""
import time

import objc
from AVFoundation import (AVSpeechBoundaryImmediate, AVSpeechSynthesisVoice, AVSpeechSynthesizer,
                          AVSpeechUtterance, AVSpeechUtteranceDefaultSpeechRate,
                          AVSpeechUtteranceMaximumSpeechRate, AVSpeechUtteranceMinimumSpeechRate)

from Foundation import NSObject

from .. import lang
from ..audio import NoAudioError
from ..engines import _Threaded


def av_rate(speed):
    """AVSpeech rates run 0..1 with 0.5 as normal speech; slower and faster scale separately."""
    normal = AVSpeechUtteranceDefaultSpeechRate
    rate = normal * speed if speed <= 1 else normal + (AVSpeechUtteranceMaximumSpeechRate - normal) * (speed - 1)
    return min(max(rate, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)


def py_offset(text, utf16):
    """A Python index into `text` from an NSString (UTF-16) index, which counts an emoji twice."""
    return len(text.encode("utf-16-le")[:utf16 * 2].decode("utf-16-le", "ignore"))


class _Words(NSObject, protocols=[objc.protocolNamed("AVSpeechSynthesizerDelegate")]):
    """Passes where each spoken word starts. AppKit's main run loop delivers it."""

    def speechSynthesizer_willSpeakRangeOfSpeechString_utterance_(self, synth, word, utterance):
        self.on_progress(py_offset(self.text, word.location))


class MacVoiceEngine(_Threaded):
    name = "macOS"
    reports_progress = True

    def speak(self, text, lang_tag, on_done, on_audio=lambda: None, on_progress=lambda chars: None):
        self._start(lambda stop: self._run(text, lang_tag or lang.detect(text), stop, on_audio, on_progress), on_done)

    def _run(self, text, tag, stop, on_audio, on_progress=lambda chars: None):
        voice = AVSpeechSynthesisVoice.voiceWithLanguage_(tag)
        if voice is None:
            raise NoAudioError(f"macOS: no installed voice for {tag}")
        synth, words = AVSpeechSynthesizer.alloc().init(), _Words.alloc().init()
        words.text, words.on_progress = text, (lambda chars: not stop.is_set() and on_progress(chars))
        synth.setDelegate_(words)  # a weak reference: `words` lives as long as this run
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
