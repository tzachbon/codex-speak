"""The Settings window: native ttk controls laid out like Windows 11 Settings. Changes apply at once."""
import json
import os
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

from PIL import ImageTk

from . import settings
from .popup import fonts

PAGE, CARD, BORDER, SUBTLE = "#f3f3f3", "#ffffff", "#e5e5e5", "#5f5f5f"
ENGINES = [(None, "Auto: Codex, then Edge, then Windows"), ("Codex", "Codex only"),
           ("Edge", "Edge only"), ("Windows", "Windows only (offline)")]


def stt_connection():
    path = Path(os.environ["LOCALAPPDATA"]) / "select-to-tts" / "stt-connection.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    url, model = data["base_url"], data["model"]
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not parsed.path.endswith("/v1") or model != "codex-realtime"):
        raise ValueError("Invalid local STT connection")
    return url, model


class SettingsWindow:
    def __init__(self, root, cfg, icon, on_change, on_test):
        self.cfg, self.on_change, self.on_test, self._save_job = cfg, on_change, on_test, None
        w = self.win = tk.Toplevel(root, bg=PAGE, padx=24, pady=20)
        w.title("Select to TTS settings")
        w.resizable(False, False)
        self._icon = ImageTk.PhotoImage(icon, master=w)
        w.iconphoto(False, self._icon)
        _, text = fonts(root)
        st = ttk.Style(w)
        st.theme_use("vista")
        for name in ("TLabel", "TCheckbutton", "Horizontal.TScale"):
            st.configure(f"Card.{name}", background=CARD, font=(text, 10))
        st.configure("Sub.Card.TLabel", foreground=SUBTLE, font=(text, 9))
        st.configure("TButton", font=(text, 10), padding=(12, 4))
        tk.Label(w, text="Settings", bg=PAGE, font=(text.replace("Text", "Display"), 20, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 12))

        self.startup = tk.BooleanVar(w, settings.startup_enabled())
        card = self._card("General")
        ttk.Checkbutton(card, text="Start Select to TTS when I sign in to Windows", style="Card.TCheckbutton",
                        variable=self.startup, command=self._startup_changed).pack(anchor="w")

        card = self._card("Reading")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        ttk.Label(row, text="Speed", style="Card.TLabel", width=8).pack(side="left")
        self.speed = tk.DoubleVar(w, cfg["speed"])
        ttk.Scale(row, from_=settings.SPEEDS[0], to=settings.SPEEDS[1], variable=self.speed, length=260,
                  style="Card.Horizontal.TScale", command=self._speed_changed).pack(side="left", padx=8)
        self.speed_lbl = ttk.Label(row, style="Card.TLabel", width=6)
        self.speed_lbl.pack(side="left")
        self._show_speed()
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Voice", style="Card.TLabel", width=8).pack(side="left")
        self.engine = ttk.Combobox(row, state="readonly", width=36, font=(text, 10),
                                   values=[label for _, label in ENGINES])
        self.engine.current([e for e, _ in ENGINES].index(cfg["engine"]))
        self.engine.bind("<<ComboboxSelected>>", self._engine_changed)
        self.engine.pack(side="left", padx=8)
        ttk.Label(card, text="Codex uses your ChatGPT sign-in and can read slower but not faster, "
                  "so above 1× Auto starts with Edge. Edge sends the text to Microsoft. "
                  "Windows voices stay on this PC.", style="Sub.Card.TLabel", wraplength=420
                  ).pack(anchor="w", pady=(8, 0))
        ttk.Button(card, text="Test voice", command=self._test).pack(anchor="w", pady=(12, 0))

        card = self._card("Selection")
        self.clip = tk.BooleanVar(w, cfg["clipboard_fallback"])
        ttk.Checkbutton(card, text="Read apps that hide their selection, such as VS Code",
                        style="Card.TCheckbutton", variable=self.clip,
                        command=lambda: self._set("clipboard_fallback", self.clip.get())).pack(anchor="w")
        ttk.Label(card, text="Copies the selection with Ctrl+C, then restores your clipboard.",
                  style="Sub.Card.TLabel").pack(anchor="w", pady=(4, 0))

        card = self._card("Speech-to-text · OpenAI-compatible")
        self.stt_values = {name: tk.StringVar(w) for name in ("Server URL", "Model")}
        self.stt_copy_buttons = []
        for name, value in self.stt_values.items():
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=name, style="Card.TLabel", width=10).pack(side="left")
            ttk.Entry(row, textvariable=value, state="readonly", width=34).pack(side="left", fill="x", expand=True, padx=8)
            button = ttk.Button(row, text="Copy", command=lambda name=name: self._copy_stt(name))
            button.pack(side="right")
            self.stt_copy_buttons.append(button)
        ttk.Label(card, text="Paste into OpenWhispr → Self-Hosted. No API key needed.\n"
                  "Transcription only: JSON or text, up to 60 seconds.",
                  style="Sub.Card.TLabel").pack(anchor="w", pady=(6, 0))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        self.stt_status = ttk.Label(row, style="Sub.Card.TLabel", wraplength=335)
        self.stt_status.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Refresh", command=self._refresh_stt).pack(side="right")

        ttk.Button(w, text="Close", command=self.close).pack(anchor="e", pady=(16, 0))
        w.protocol("WM_DELETE_WINDOW", self.close)
        self.focus()

    def _card(self, title):
        tk.Label(self.win, text=title, bg=PAGE, anchor="w",
                 font=tkfont.Font(family=fonts(self.win)[1], size=10, weight="bold")
                 ).pack(fill="x", pady=(8, 4))
        card = tk.Frame(self.win, bg=CARD, padx=16, pady=14, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER)
        card.pack(fill="x")
        return card

    @property
    def alive(self):
        return bool(self.win.winfo_exists())

    def focus(self):
        self._refresh_stt()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def _refresh_stt(self):
        try:
            values = stt_connection()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            values = ("", "")
        for variable, value in zip(self.stt_values.values(), values):
            variable.set(value)
        for button in self.stt_copy_buttons:
            button["state"] = "normal" if values[0] else "disabled"
        self.stt_status["text"] = ("Saved details. Refresh after restarting the server." if values[0]
                                   else "Start the local STT server, then Refresh.")

    def _copy_stt(self, name):
        self._refresh_stt()
        value = self.stt_values[name].get()
        if value:
            self.win.clipboard_clear()
            self.win.clipboard_append(value)
            self.stt_status["text"] = f"{name} copied."

    def close(self):
        if self._save_job:
            self.win.after_cancel(self._save_job)
            self._set("speed", self.cfg["speed"])
        self.win.destroy()

    def _set(self, key, value):
        self.cfg[key] = value
        self.on_change(key, value)

    def _startup_changed(self):
        try:
            settings.set_startup(self.startup.get())
        except OSError as e:
            self.startup.set(settings.startup_enabled())
            messagebox.showerror("Select to TTS", f"Could not change sign-in startup: {e}", parent=self.win)

    def _show_speed(self):
        self.speed_lbl["text"] = settings.speed_label(self.speed.get())

    def set_speed(self, speed):
        """Mirrors a speed picked in the popup, without saving it again."""
        self.speed.set(speed)
        self.cfg["speed"] = speed
        self._show_speed()

    def _speed_changed(self, _value):
        self.speed.set(round(self.speed.get() * 20) / 20)  # 0.05 steps
        self._show_speed()
        self.cfg["speed"] = self.speed.get()
        self.on_change("speed", self.cfg["speed"], False)  # the next read uses it at once
        if self._save_job:
            self.win.after_cancel(self._save_job)
        self._save_job = self.win.after(400, self._save_speed)  # don't save on every pixel of a drag

    def _save_speed(self):
        self._save_job = None
        self._set("speed", self.cfg["speed"])

    def _engine_changed(self, _e):
        self._set("engine", ENGINES[self.engine.current()][0])
        self.engine.selection_clear()

    def _test(self):
        if self._save_job:
            self.win.after_cancel(self._save_job)
            self._save_speed()
        self.on_test(f"This is how Select to TTS sounds at {self.speed_lbl['text']} speed.")
