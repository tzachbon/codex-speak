"""The transcript chain for dictation: Cursor then Codex by default, in the saved order, skipping unready sources."""
import logging

from . import codex_rt, stt
from .llm_cursor import CursorStt

log = logging.getLogger("harness_discussion")


class Error(Exception):
    """Safe to show: never contains the transcript."""


class CodexStt:
    name = "Codex"

    def status(self):
        return codex_rt.login_status()

    def transcribe(self, audio, language=""):
        return stt.transcribe(audio, language=language)


def sources():
    return [CodexStt(), CursorStt()]


def transcribe(audio, chain, order, language=""):
    """(text, source name) from the first source that returns words."""
    by_name = {s.name: s for s in chain}
    for name, enabled in order:
        source = by_name.get(name)
        if not (enabled and source) or source.status() != "ready":
            continue
        try:
            text = source.transcribe(audio, language=language)
        except Exception as e:
            log.info("%s transcript failed: %s", name, type(e).__name__)
            continue
        if text and text.strip():
            return text.strip(), name
        log.info("%s transcript was empty", name)
    raise Error("No source could transcribe the recording.")
