"""The Writer: rewrites the selection in place with a mode, then offers Undo, Review, and another mode.

Runs where the host provides `edit` (capture, same_context, replace, select_back, collapse), a toast, a review
panel, and an Esc watcher. The rewrite runs on a worker thread. Pasting happens on the main thread, and only
when the app, window, and selection are still the ones captured.
"""
import logging
import sys
import threading
import time

from . import edit_logic, lang, writer
from .llm_codex import CodexWriter
from .llm_cursor import CursorWriter
from .summarize import LocalWriter

log = logging.getLogger("harness_discussion")
DOUBLE_PRESS_S = 0.35
UNDO_KEYS = "Cmd+Z" if sys.platform == "darwin" else "Ctrl+Z"


def _edges(text):
    """(leading, trailing) whitespace, kept around the rewrite so a selected line keeps its line break."""
    core = text.strip()
    if not core:
        return text, ""
    start = text.index(core)
    return text[:start], text[start + len(core):]


class Writer:
    rewriting, writer_ready = False, False

    def _init_writer(self):
        self.edit = getattr(self.host, "edit", None)
        self.writer_ready = self.edit is not None
        self.writer_sources = [CursorWriter(), CodexWriter(), LocalWriter(self.summary_server)]
        self._rewrite_id, self._rewrite_cancel, self.rewriting = 0, threading.Event(), False
        self._last_edit = None  # (ctx, original, inserted, mode) of the latest in-place rewrite
        self._press_at, self._press_gen, self._escaped_at = 0.0, 0, 0.0
        self.toast = self.review = self._esc = None
        if self.writer_ready:
            self.toast, self.review = self.host.make_toast(), self.host.make_review()
            self.toast.on_hide = self._watch_escape
            self._esc = self.host.esc_watcher(self._escape)

    def mode_names(self):
        return [m.name for m in writer.all_modes(self.cfg["modes"])]

    def _find_mode(self, name):
        modes = writer.all_modes(self.cfg["modes"])
        return writer.find_mode(name or self.cfg["default_mode"], modes)

    def _anchor(self):
        if self.popup.visible:
            x, y, h = self.popup.anchor()
            return x, y
        x, y = self.host.pointer()
        return x + 12, y + 16

    def _toast(self, message, actions=(), busy=False, at=None):
        x, y = at or self._anchor()
        self.toast.show(message, x, y, actions, busy)
        self._watch_escape()

    def _watch_escape(self):
        if self._esc:
            self._esc.start() if self.rewriting or self.toast.visible else self._esc.stop()

    def rewrite_from_bar(self, text, mode_name):
        self.rewrite_selection(mode_name)

    def rewrite_selection(self, mode_name=None, prev=None):
        """Captures the selection, rewrites it on a worker, and hands the result to `_rewrite_done`.
        prev: (ctx, original, inserted) to rewrite the original again in place of the inserted text."""
        if not (self.writer_ready and self.cfg["writer"]) or self.rewriting:
            return
        mode = self._find_mode(mode_name)
        at = self._anchor()
        self._rewrite_id += 1
        rid, cancel = self._rewrite_id, threading.Event()
        self._rewrite_cancel = cancel
        self._set_rewriting(True)
        self.popup.set_last_mode(mode.name)
        self._summary_gen += 1  # a summary's idle stop must not stop the local model under this rewrite
        sources = writer.chain(self.writer_sources, self.cfg["writer_sources"])
        models, clipboard = self.cfg["writer_models"], self.cfg["clipboard_fallback"]
        self._toast(f"Rewriting · {mode.name}", busy=True, at=at)

        def work():
            ctx = prev[0] if prev else None
            try:
                if prev is None:
                    ctx = self.edit.capture(clipboard)
                    if ctx is not None and ctx.secure:
                        raise writer.Error("Password fields are never rewritten.")
                    if ctx is None or not ctx.text.strip():
                        raise writer.Error("Select text to rewrite.")
                text = prev[1] if prev else ctx.text
                language = lang.name(lang.detect(text)) or "the language of the text"
                result = writer.rewrite(text, mode, sources, models=models, cancelled=cancel.is_set, language=language)
            except Exception as e:
                result = e
            self.events.put(("rewrite", rid, ctx, mode.name, result, prev, at))
        threading.Thread(target=work, daemon=True).start()

    def _set_rewriting(self, on):
        self.rewriting = on
        self.popup.set_rewriting(on)
        self._watch_escape()

    def _rewrite_done(self, rid, ctx, mode, result, prev, at):
        if rid != self._rewrite_id:
            return
        self._set_rewriting(False)
        self._arm_summary_stop()
        if isinstance(result, writer.Cancelled):
            self.toast.hide()
            return
        if isinstance(result, Exception):
            message = str(result) if isinstance(result, writer.Error) else "Could not rewrite this text."
            log.info("rewrite failed: %s", type(result).__name__)
            self._toast(message, at=at)
            return
        new, source = result
        original = prev[1] if prev else ctx.text
        lead, trail = _edges(original)
        inserted = lead + new + trail
        builtin = mode in {m.name for m in writer.BUILTIN_MODES}
        log.info("rewrote %d chars with %s in mode %s", len(original), source, mode if builtin else "custom")
        copy = lambda: self.host.copy_text(inserted)
        review_copy = lambda: self.review.show(original, inserted, None, self.host.copy_text)
        self.popup.hide()
        if prev:
            placed = edit_logic.undo(self.edit, ctx, inserted, prev[2], self.edit.NEWLINE)
        elif not self.edit.same_context(ctx):
            self._toast("Text changed. Copy the rewrite?", [("Copy", copy), ("Review", review_copy)], at=at)
            return
        else:
            placed = self.edit.replace(inserted)
        if not placed:
            self._toast("Couldn't paste here.", [("Copy", copy), ("Review", review_copy)], at=at)
            return
        self._last_edit = (ctx, original, inserted, mode)
        modes = [(m, lambda m=m: self._rewrite_again(m), m == mode) for m in self.mode_names()]
        self._toast(f"{mode} · {source}", [("Undo", self.undo_last), ("Review", self.open_review),
                                           ("Mode", modes)], at=at)

    def _rewrite_again(self, mode_name):
        if self._last_edit:
            ctx, original, inserted, _ = self._last_edit
            self.rewrite_selection(mode_name, prev=(ctx, original, inserted))

    def undo_last(self):
        if not self._last_edit:
            return
        ctx, original, inserted, _ = self._last_edit
        if edit_logic.undo(self.edit, ctx, original, inserted, self.edit.NEWLINE):
            self._last_edit = None
            self._toast("Original restored.")
        else:
            self._toast(f"The text changed. Use {UNDO_KEYS}.")

    def open_review(self):
        if not self._last_edit:
            return
        ctx, original, inserted, mode = self._last_edit

        def replace(text):
            if edit_logic.undo(self.edit, ctx, text, inserted, self.edit.NEWLINE):
                self._last_edit = (ctx, original, text, mode)
            else:
                self._toast("The text changed. Copy the result?", [("Copy", lambda: self.host.copy_text(text))])
        self.review.show(original, inserted, replace, self.host.copy_text)

    def _rewrite_hotkey(self):
        """One press rewrites with the default mode. A second press within 350 ms shows the mode menu."""
        now = time.monotonic()
        self._press_gen += 1
        gen = self._press_gen
        if now - self._press_at < DOUBLE_PRESS_S:
            self._press_at = 0.0
            self.host.pick_mode(self.mode_names(), self.cfg["default_mode"], self.rewrite_selection)
            return
        self._press_at = now
        self.host.after(int(DOUBLE_PRESS_S * 1000), lambda: gen == self._press_gen and self.rewrite_selection())

    def _escape(self):
        """Esc cancels a rewrite, else hides the toast, else dismisses the bar. Both watchers can see one Esc."""
        now = time.monotonic()
        if now - self._escaped_at < 0.15:
            return
        self._escaped_at = now
        if self.rewriting:
            self._rewrite_cancel.set()
            self._rewrite_id += 1
            self._set_rewriting(False)
            self._arm_summary_stop()
            self.toast.hide()
        elif self.toast and self.toast.visible:
            self.toast.hide()
        elif self.popup.visible:
            self.popup.close()

    def _close_writer(self):
        self._rewrite_cancel.set()
        for source in self.writer_sources:
            close = getattr(source, "close", None)
            if close:
                close()
        if self._esc:
            self._esc.stop()
            self.host.set_shortcut("rewrite", "", None)
