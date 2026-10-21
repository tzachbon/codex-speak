"""Settings shortcut rows (read, rewrite, dictate), with Change… recording the next key combination."""
import tkinter as tk
from tkinter import ttk

from .. import hotkeys
from .sources_ui import CARD
from .trigger import VK

TK_MODS = {"shift": 0x1, "ctrl": 0x4, "alt": 0x20000}  # Tk's event.state bits on Windows
KEYS = {vk: name for name, vk in VK.items()}  # Tk's keycode is the virtual key, the same under any layout
TITLES = {"hotkey": "Read shortcut", "rewrite_hotkey": "Rewrite shortcut", "dictate_hotkey": "Hold to dictate"}

class ShortcutRow:
    """Mixed into SettingsWindow, which owns win, cfg, on_record and _set."""

    def _shortcut_row(self, card, key="hotkey",
                      note="Reads the selected text without clicking the bar. Pressing it again stops the read."):
        if not hasattr(self, "shortcuts"):
            self.shortcuts = {}
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text=TITLES[key], style="Card.TLabel").pack(side="left")
        widgets = self.shortcuts[key] = {
            "off": ttk.Button(row, text="Off", command=lambda: self._set_hotkey("", key)),
            "change": ttk.Button(row, text="Change…", command=lambda: self._record_hotkey(key)),
            "label": ttk.Label(row, text=hotkeys.label(self.cfg[key]), style="Card.TLabel")}
        widgets["off"].pack(side="right")
        widgets["change"].pack(side="right", padx=(0, 8))
        widgets["label"].pack(side="right", padx=(0, 8))
        widgets["error"] = ttk.Label(card, style="Sub.Card.TLabel", foreground="#c42b1c")
        widgets["error"].pack(anchor="w")
        if key == "hotkey":
            self.hotkey_lbl = widgets["label"]
        ttk.Label(card, text=note, style="Sub.Card.TLabel", wraplength=440).pack(anchor="w", pady=(4, 0))

    def _record_hotkey(self, key="hotkey"):
        """Change…: the next key combination with a modifier becomes the shortcut; Esc keeps the old one."""
        self._recording = key
        self.shortcuts[key]["label"]["text"] = "Press keys…"
        self.shortcuts[key]["error"]["text"] = ""
        self.on_record(True)  # so pressing a current shortcut records it instead of acting on it
        self.win.focus_force()
        self.win.bind("<KeyPress>", self._hotkey_key)

    def _hotkey_key(self, event):
        if event.keysym == "Escape":
            self._set_hotkey(self.cfg[self._recording])
        elif (key := KEYS.get(event.keycode)) and (
                spec := hotkeys.spec({m for m, bit in TK_MODS.items() if event.state & bit}, key)):
            self._set_hotkey(spec)
        return "break"

    def _set_hotkey(self, spec, key=None):
        key = key or getattr(self, "_recording", "hotkey")
        self.win.unbind("<KeyPress>")
        used = next((k for k in self.shortcuts if k != key and spec and hotkeys.parse(self.cfg.get(k))
                     == hotkeys.parse(spec)), None)
        if used:  # two shortcuts on one chord would both fire
            self.shortcuts[key]["error"]["text"] = f"{TITLES[used]} already uses {hotkeys.label(spec)}."
            spec = self.cfg[key]
        if spec != self.cfg[key]:
            self._set(key, spec)
        for k, widgets in self.shortcuts.items():  # also ends a recording another row started
            widgets["label"]["text"] = hotkeys.label(self.cfg[k])
        self.on_record(False)
