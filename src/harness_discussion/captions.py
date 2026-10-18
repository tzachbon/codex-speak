"""App's read-along caption: Codex's transcript, or a piece stepped sentence by sentence."""
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

    def _step_captions(self, rid, index, parts):
        """Steps a piece's caption sentence by sentence, as Cursor and Edge send no word timings."""
        if rid != self._read_id or index != self._unit_index or not self._read_options:
            return
        if self.popup.paused:
            self._caption_steps = lambda: self._step_captions(rid, index, parts)
            return
        self.popup.set_caption(parts[0])
        if parts[1:]:
            ms = int(len(parts[0]) / (CAPTION_CHARS_S * self.cfg["speed"]) * 1000)
            self.host.after(ms, lambda: self._step_captions(rid, index, parts[1:]))

    def _show_caption(self, text):
        if text != self._last_caption:
            self._last_caption = text
            self.popup.set_caption(text)
