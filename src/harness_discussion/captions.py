"""App's read-along caption: Codex's transcript, or a piece stepped sentence by sentence."""
import time

from . import sentences

CAPTION_CHARS_S = 15  # shortcut: an estimate of spoken characters a second at 1×; use engine timings if they appear


class Captions:
    """Mixed into core.App, which owns popup, host, cfg and the read state."""

    def _caption(self, rid, index, transcript):
        """Shows the sentence Codex is speaking, held while paused because the transcript keeps arriving."""
        if rid != self._read_id or index != self._unit_index or not self._read_options:
            return
        if self.popup.paused:
            self._held_caption = sentences.current(transcript)
        else:
            self._show_caption(sentences.current(transcript))

    def _step_captions(self, rid, index, parts, ms=None):
        """Steps a piece's caption sentence by sentence, as Cursor and Edge send no word timings.

        `ms` resumes a paused step: the time it still had left before the next sentence."""
        self._caption_steps = None
        if rid != self._read_id or index != self._unit_index or not self._read_options:
            return
        if ms is None:
            if self.popup.paused:
                self._caption_held = (rid, index, parts, None)
                return
            self._show_caption(parts[0])
            ms = int(len(parts[0]) / (CAPTION_CHARS_S * self._read_options[2]) * 1000)  # the read's own speed
            parts = parts[1:]
        if parts:
            step = self._caption_steps = (rid, index, parts, time.monotonic() + ms / 1000)
            self.host.after(ms, lambda: self._caption_steps is step and self._step_captions(rid, index, parts))

    def _follow_progress(self, rid, index, chars):
        """Shows the sentence the engine says it is speaking, which replaces the estimated steps."""
        if rid != self._read_id or index != self._unit_index or not self._read_options:
            return
        self._caption_steps = self._caption_held = None
        text = sentences.at(self._units[index], chars)
        if self.popup.paused:
            self._held_caption = text  # a position queued as the user paused shows on resume
        else:
            self._show_caption(text)

    def _hold_captions(self):
        """Pause stops the step timer and keeps what was left of it."""
        step, self._caption_steps = self._caption_steps, None
        if step:
            self._caption_held = (*step[:3], max(0, int((step[3] - time.monotonic()) * 1000)))

    def _resume_captions(self):
        held, self._caption_held = self._caption_held, None
        if held:
            self._step_captions(*held)

    def _show_caption(self, text):
        if text != self._last_caption:
            self._last_caption = text
            self.popup.set_caption(text)
