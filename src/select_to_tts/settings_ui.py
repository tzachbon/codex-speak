"""The Settings window: native ttk controls laid out like Windows 11 Settings. Changes apply at once."""
import json
import os
import sys
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

from PIL import ImageTk

from . import settings, updates
from .popup import fonts, work_area

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
    def __init__(self, root, cfg, icon, on_change, on_test, stt_state=lambda: None,
                 update_state=lambda: ("Ready to check.", False), on_update=lambda: None):
        self.cfg, self.on_change, self.on_test, self._save_job, self._pending_key = cfg, on_change, on_test, None, None
        self.stt_state = stt_state  # None when running, else why not
        self.update_state = update_state
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

        self.footer = tk.Frame(w, bg=PAGE)
        self.close_button = ttk.Button(self.footer, text="Close", command=self.close)
        self.close_button.pack(anchor="e", pady=(16, 0))
        self.footer.pack(side="bottom", fill="x")
        self._scroll_frame = tk.Frame(w, bg=PAGE)
        self._scroll_canvas = tk.Canvas(self._scroll_frame, bg=PAGE, bd=0, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(self._scroll_frame, orient="vertical",
                                        command=self._scroll_canvas.yview)
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)
        self.content = tk.Frame(self._scroll_canvas, bg=PAGE)
        self._content_window = self._scroll_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _e: self._scroll_canvas.configure(
            scrollregion=self._scroll_canvas.bbox("all")))
        self._scroll_canvas.bind("<Configure>", lambda e: self._scroll_canvas.itemconfigure(
            self._content_window, width=e.width))
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scroll_frame.pack(fill="both", expand=True)

        tk.Label(self.content, text="Settings", bg=PAGE, font=(text.replace("Text", "Display"), 20, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 12))

        self.startup = tk.BooleanVar(w, settings.startup_enabled())
        card = self._card("General")
        ttk.Checkbutton(card, text="Start Select to TTS when I sign in to Windows", style="Card.TCheckbutton",
                        variable=self.startup, command=self._startup_changed).pack(anchor="w")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text=f"Select to TTS {updates.current_version()}", style="Card.TLabel").pack(side="left")
        self.update_button = ttk.Button(row, text="Check and install update", command=on_update)
        self.update_button.pack(side="right")
        self.auto_update = tk.BooleanVar(w, cfg.get("auto_update", False))
        self.auto_update_button = ttk.Checkbutton(card, text="Install updates automatically", style="Card.TCheckbutton",
            variable=self.auto_update, command=lambda: self._set("auto_update", self.auto_update.get()))
        self.auto_update_button.pack(anchor="w", pady=(8, 0))
        self.update_status = ttk.Label(card, style="Sub.Card.TLabel", wraplength=420)
        self.update_status.pack(anchor="w", pady=(4, 0))

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

        card = self._card("Captions")
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x")
        ttk.Label(row, text="Font size", style="Card.TLabel", width=12).pack(side="left")
        self.caption_font_value = tk.StringVar(w, str(cfg["caption_font_size"]))
        self.caption_font_size = ttk.Spinbox(row, from_=8, to=24, increment=1, width=5,
                                             textvariable=self.caption_font_value,
                                             command=self._caption_font_changed)
        self.caption_font_size.bind("<Return>", self._caption_font_changed)
        self.caption_font_size.bind("<FocusOut>", self._caption_font_changed)
        self.caption_font_size.pack(side="left", padx=8)
        self.caption_background = tk.BooleanVar(w, cfg["caption_background"])
        self.caption_background_check = ttk.Checkbutton(
            card, text="Show a background behind captions", style="Card.TCheckbutton",
            variable=self.caption_background, command=self._caption_background_changed)
        self.caption_background_check.pack(anchor="w", pady=(10, 0))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Background opacity", style="Card.TLabel", width=17).pack(side="left")
        self.caption_opacity = tk.DoubleVar(w, round(cfg["caption_background_opacity"] * 100))
        self.caption_opacity_scale = ttk.Scale(row, from_=0, to=100, variable=self.caption_opacity,
                                               length=210, style="Card.Horizontal.TScale")
        self.caption_opacity_scale.pack(side="left", padx=8)
        self.caption_opacity_label = ttk.Label(row, style="Card.TLabel", width=5)
        self.caption_opacity_label.pack(side="left")
        self.caption_opacity.trace_add("write", self._caption_opacity_changed)
        self._caption_opacity_changed()
        self._caption_opacity_state()

        card = self._card("Selection")
        self.clip = tk.BooleanVar(w, cfg["clipboard_fallback"])
        ttk.Checkbutton(card, text="Read apps that hide their selection, such as VS Code",
                        style="Card.TCheckbutton", variable=self.clip,
                        command=lambda: self._set("clipboard_fallback", self.clip.get())).pack(anchor="w")
        ttk.Label(card, text="Copies the selection with Ctrl+C, then restores your clipboard.",
                  style="Sub.Card.TLabel").pack(anchor="w", pady=(4, 0))
        self.prefetch = tk.BooleanVar(w, cfg["prefetch"])
        ttk.Checkbutton(card, text="Prepare speech as soon as I select text", style="Card.TCheckbutton",
                        variable=self.prefetch,
                        command=lambda: self._set("prefetch", self.prefetch.get())).pack(anchor="w", pady=(12, 0))
        ttk.Label(card, text="Sends the selected text to Microsoft's speech service before you press play. "
                  "Applies when Edge reads: Edge only, or Auto above 1×.", style="Sub.Card.TLabel",
                  wraplength=420).pack(anchor="w", pady=(4, 0))

        card = self._card("Speech-to-text · OpenAI-compatible")
        self.stt_on = tk.BooleanVar(w, cfg.get("stt_server", False))
        ttk.Checkbutton(card, text="Run the speech-to-text server for other apps, such as OpenWhispr",
                        style="Card.TCheckbutton", variable=self.stt_on,
                        command=self._stt_toggled).pack(anchor="w", pady=(0, 6))
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
        ttk.Label(card, text="Paste into OpenWhispr → Self-Hosted. No API key needed. The URL stays\n"
                  "the same after restarts. Transcription only: JSON or text, up to 60 seconds.",
                  style="Sub.Card.TLabel").pack(anchor="w", pady=(6, 0))
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(6, 0))
        self.stt_status = ttk.Label(row, style="Sub.Card.TLabel", wraplength=335)
        self.stt_status.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Refresh", command=self._refresh_stt).pack(side="right")

        w.protocol("WM_DELETE_WINDOW", self.close)
        self._fit_work_area(root)
        self.focus()

    def _card(self, title):
        tk.Label(self.content, text=title, bg=PAGE, anchor="w",
                 font=tkfont.Font(family=fonts(self.win)[1], size=10, weight="bold")
                 ).pack(fill="x", pady=(8, 4))
        card = tk.Frame(self.content, bg=CARD, padx=16, pady=14, highlightthickness=1,
                        highlightbackground=BORDER, highlightcolor=BORDER)
        card.pack(fill="x")
        return card

    def _fit_work_area(self, root):
        self.win.update_idletasks()
        width, content_height = self.content.winfo_reqwidth(), self.content.winfo_reqheight()
        self._scroll_canvas.configure(width=width, height=content_height)
        self.win.update_idletasks()
        area = work_area(root.winfo_pointerx(), root.winfo_pointery())
        area_width, area_height = area.right - area.left, area.bottom - area.top
        requested_height = self.win.winfo_reqheight()
        max_height = max(1, area_height - 48)  # room for the native title bar and borders
        visible_content_height = max(1, content_height - max(0, requested_height - max_height))
        if visible_content_height < content_height:
            self._scroll_canvas.configure(height=visible_content_height)
            self._scrollbar.pack(side="right", fill="y")
        self.win.update_idletasks()
        width, height = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x = area.left + max(0, (area_width - width) // 2)
        y = area.top + max(0, (area_height - height) // 2)
        self.win.geometry(f"{width}x{height}+{x}+{y}")

    @property
    def alive(self):
        return bool(self.win.winfo_exists())

    def focus(self):
        self._refresh_stt()
        self.refresh_updates()
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def refresh_updates(self):
        text, busy = self.update_state()
        installed = getattr(sys, "frozen", False)
        self.update_button["state"] = "normal" if installed and not busy else "disabled"
        self.auto_update_button["state"] = "normal" if installed else "disabled"
        self.update_status["text"] = text if installed else "Updates are available in installed builds."

    def _refresh_stt(self):
        try:
            values = stt_connection()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            values = ("", "")
        for variable, value in zip(self.stt_values.values(), values):
            variable.set(value)
        for button in self.stt_copy_buttons:
            button["state"] = "normal" if values[0] else "disabled"
        problem = self.stt_state()
        self.stt_status["text"] = (problem if problem else "Running." if values[0]
                                   else "Turn on the server above.")

    def _stt_toggled(self):
        self._set("stt_server", self.stt_on.get())
        self.win.after(300, self._refresh_stt)

    def _copy_stt(self, name):
        self._refresh_stt()
        value = self.stt_values[name].get()
        if value:
            self.win.clipboard_clear()
            self.win.clipboard_append(value)
            self.stt_status["text"] = f"{name} copied."

    def close(self):
        self._flush_pending()
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
        self._schedule_save("speed")

    def _schedule_save(self, key):
        if self._save_job:
            self.win.after_cancel(self._save_job)
        self._pending_key = key
        self._save_job = self.win.after(400, self._save_pending)

    def _save_pending(self):
        self._save_job = None
        key, self._pending_key = self._pending_key, None
        if key is not None:
            self._set(key, self.cfg[key])

    def _flush_pending(self):
        self._caption_font_changed()
        if self._save_job:
            self.win.after_cancel(self._save_job)
            self._save_pending()

    def _set_debounced(self, key, value):
        if self.cfg[key] == value:
            return
        self.cfg[key] = value
        self.on_change(key, value, False)
        self._schedule_save(key)

    def _caption_font_changed(self, _event=None):
        try:
            value = int(self.caption_font_value.get())
        except ValueError:
            self.caption_font_value.set(str(self.cfg["caption_font_size"]))
            return "break"
        value = min(max(value, 8), 24)
        self.caption_font_value.set(str(value))
        self._set_debounced("caption_font_size", value)
        return "break"

    def _caption_background_changed(self):
        self._set_debounced("caption_background", self.caption_background.get())
        self._caption_opacity_state()

    def _caption_opacity_changed(self, *_):
        percent = min(max(round(self.caption_opacity.get()), 0), 100)
        if self.caption_opacity.get() != percent:
            self.caption_opacity.set(percent)
        self.caption_opacity_label["text"] = f"{percent}%"
        self._set_debounced("caption_background_opacity", percent / 100)

    def _caption_opacity_state(self):
        self.caption_opacity_scale.configure(
            state="normal" if self.caption_background.get() else "disabled")

    def _engine_changed(self, _e):
        self._set("engine", ENGINES[self.engine.current()][0])
        self.engine.selection_clear()

    def _test(self):
        self._flush_pending()
        self.on_test(f"This is how Select to TTS sounds at {self.speed_lbl['text']} speed.")
