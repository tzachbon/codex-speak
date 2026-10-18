"""The Sources rows of the Windows Settings window: order, enable, voice, status and Test per source."""
import tkinter as tk
from tkinter import ttk

from PIL import ImageTk

from .. import icons, settings
from ..sources import fix as source_fix

CARD = "#ffffff"


class SourcesSection:
    """Mixed into SettingsWindow, which owns win, cfg, statuses, _engines, _set, _flush_pending, on_play and on_fix."""

    def _sources_section(self, card, font, welcome):
        self.welcome = None
        if welcome:  # first run: point new users at the voices
            self.welcome = ttk.Label(card, text=settings.WELCOME, style="Card.TLabel", font=(font, 11, "bold"))
            self.welcome.pack(anchor="w", pady=(12, 0))
        self.sources_frame = tk.Frame(card, bg=CARD)
        self.sources_frame.pack(fill="x", pady=(12, 0))
        self.source_icons = {}  # Tk drops an image nothing in Python refers to
        self.source_rows = {name: self._source_row(name, font) for name, _ in self.cfg["sources"]}
        self.refresh_sources()

    def _source_row(self, name, font):
        """(enabled, status, voice picker or None, widgets in column order) for one voice source."""
        f, on = self.sources_frame, tk.BooleanVar(self.win)
        choices = getattr(self._engines.get(name), "voices", ())
        voice = ttk.Combobox(f, state="readonly", width=9, font=(font, 10),
                             values=[label for _, label in choices]) if choices else None
        if voice:
            voice.bind("<<ComboboxSelected>>", lambda _e: self._voice_changed(name))
        self.source_icons[name] = ImageTk.PhotoImage(icons.source_image(name, 20), master=self.win)
        widgets = [
            ttk.Checkbutton(f, text=f" {name}", style="Card.TCheckbutton", variable=on, width=9,
                            image=self.source_icons[name], compound="left",
                            command=lambda: self._source_toggled(name)),
            ttk.Label(f, style="Sub.Card.TLabel", width=20, wraplength=140),
            voice or ttk.Label(f, text="Default voice" if name == "Codex" else "", style="Sub.Card.TLabel"),
            ttk.Button(f, text="Test", width=5, command=lambda: self._test_source(name)),
            ttk.Button(f, text="↑", width=2, command=lambda: self._move(name, -1)),
            ttk.Button(f, text="↓", width=2, command=lambda: self._move(name, 1)),
            ttk.Button(f, width=9, command=lambda: self.on_fix(name))]  # Install… or Sign in…, when needed
        return on, widgets[1], voice, widgets

    def refresh_sources(self):
        """Shows the rows in the saved order, with the statuses core last checked."""
        statuses, sources = self.statuses(), self.cfg["sources"]
        for i, (name, enabled) in enumerate(sources):
            on, status, voice, widgets = self.source_rows[name]
            on.set(enabled)
            status["text"] = settings.status_text(statuses.get(name))
            if voice:
                engine = self._engines[name]
                ids = [v for v, _ in engine.voices]
                chosen = self.cfg["voices"].get(name)
                chosen = chosen if chosen in ids else getattr(engine, "default_voice", ids[0])
                voice.current(ids.index(chosen))
            for column, widget in enumerate(widgets):
                widget.grid(row=i, column=column, sticky="w", padx=(0, 6), pady=2)
            found = source_fix(name, statuses.get(name))
            widgets[6]["text"] = found[0] if found else ""
            if not found:
                widgets[6].grid_remove()
            widgets[4]["state"] = "normal" if i else "disabled"
            widgets[5]["state"] = "normal" if i < len(sources) - 1 else "disabled"
        self._refresh_nav()

    def set_sources(self, sources):
        """Mirrors an order changed elsewhere, without saving it again."""
        self.cfg["sources"] = sources
        self.refresh_sources()

    def _set_sources(self, sources):
        self._set("sources", sources)
        self.refresh_sources()

    def _source_toggled(self, name):
        on = self.source_rows[name][0].get()
        self._set_sources([[n, on if n == name else was] for n, was in self.cfg["sources"]])

    def _move(self, name, step):
        sources = [list(s) for s in self.cfg["sources"]]
        i = [n for n, _ in sources].index(name)
        if 0 <= i + step < len(sources):
            sources[i], sources[i + step] = sources[i + step], sources[i]
            self._set_sources(sources)

    def _voice_changed(self, name):
        voice = self.source_rows[name][2]
        self._set("voices", {**self.cfg["voices"], name: self._engines[name].voices[voice.current()][0]})
        voice.selection_clear()

    def _test_source(self, name):
        self._flush_pending()
        self.on_play(name)
