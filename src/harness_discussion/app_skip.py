"""App's ⏮ and ⏭, and the read shortcut's selection read."""


def offset(text, units, index):
    """Where units[index] starts in text; units come from sentences.split, so each is found in order."""
    at = 0
    for unit in units[:index]:
        at = text.index(unit, at) + len(unit)
    return text.index(units[index], at) if index < len(units) else len(text)


class Skips:
    """Mixed into core.App, which owns popup, host, cfg and the read state."""

    def skip(self, delta):
        """⏮ (-1) and ⏭ (+1): read again from the previous or next sentence; past the last one stops."""
        if not self._read_options:
            return
        index = max(0, self._sentence + delta)
        if index >= len(self._sentences):
            self.stop()
            return
        self.play(self._read_text, self._read_options[0], start=index)
        self.popup.set_playing(True)
        self.popup.schedule_hide()  # cancels the hide timer that stop() set
        self.popup.set_loading(True)

    def _track(self, caption):
        """Moves the skip position to the sentence shown; a caption that matches none (Codex rewords) keeps it.

        After the first match the search starts past the current sentence, so "Go. Go." moves to the second one."""
        start = self._sentence + self._tracked
        if caption in self._sentences[start:]:
            self._sentence, self._tracked = self._sentences.index(caption, start), True

    def _hotkey_read(self, x, y):
        try:
            text = self.host.read_selection(self.cfg["clipboard_fallback"])
        except Exception:
            text = None
        self.events.put(("hotkey_read", text, x, y))
