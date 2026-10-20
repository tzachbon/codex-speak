"""App's read-along caption: Codex's transcript, or a piece stepped sentence by sentence."""
import time

from . import sentences

CAPTION_CHARS_S = 15  # shortcut: an estimate of spoken characters a second at 1×; use engine timings if they appear


class Captions:
    """Mixed into core.App, which owns popup, host, cfg and the read state."""
    _heard = (0, "")  # Codex: sentences in the transcript and the caption tracked last; play() resets it

    def _caption(self, rid, index, transcript):
        """Shows the sentence Codex is speaking, held while paused because the transcript keeps arriving."""
        if rid != self._read_id or index != self._unit_index or not self._read_options:
            return
        units, text = sentences.split(transcript), sentences.current(transcript)
        unit = text if text in units else units[-1]  # "2. Two." joins two units; track the item's own
        if unit != self._heard[1] or (len(units) > self._heard[0] and units[-1] == unit):  # "Go. Go." moves on
            self._track(unit)
        self._heard = (len(units), unit)
        if self.popup.paused:
            self._held_caption = text
        else:
            self._display(text)

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
            # a Codex fallback tracks its own transcript, so its estimated steps only show the caption
            (self._display if self.chain.active_name == "Codex" else self._show_caption)(parts[0], step=True)
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
        self._track_at(index, chars)
        if self.popup.paused:
            self._held_caption = text  # a position queued as the user paused shows on resume
        else:
            self._display(text)

    def _hold_captions(self):
        """Pause stops the step timer and keeps what was left of it."""
        step, self._caption_steps = self._caption_steps, None
        if step:
            self._caption_held = (*step[:3], max(0, int((step[3] - time.monotonic()) * 1000)))

    def _resume_captions(self):
        held, self._caption_held = self._caption_held, None
        if held:
            self._step_captions(*held)

    def _show_caption(self, text, step=False):
        """step: a new sentence of the estimated steps, tracked even when it repeats the one before."""
        if step or text != self._last_caption:
            self._track(text)
        self._display(text)

    def _display(self, text, step=False):
        """Shows a caption already tracked."""
        if text != self._last_caption:
            self._last_caption = text
            self.popup.set_caption(text)
