"""Settings → Reading: the read shortcut, with Change… recording the next key combination."""
import tkinter as tk
from tkinter import ttk

from .. import hotkeys
from .sources_ui import CARD
from .trigger import VK

TK_MODS = {"shift": 0x1, "ctrl": 0x4, "alt": 0x20000}  # Tk's event.state bits on Windows
KEYS = {vk: name for name, vk in VK.items()}  # Tk's keycode is the virtual key, the same under any layout


class ShortcutRow:
    """Mixed into SettingsWindow, which owns win, cfg and _set."""

    def _shortcut_row(self, card):
        row = tk.Frame(card, bg=CARD)
        row.pack(fill="x", pady=(12, 0))
        ttk.Label(row, text="Read shortcut", style="Card.TLabel").pack(side="left")
        ttk.Button(row, text="Off", command=lambda: self._set_hotkey("")).pack(side="right")
        ttk.Button(row, text="Change…", command=self._record_hotkey).pack(side="right", padx=(0, 8))
        self.hotkey_lbl = ttk.Label(row, text=hotkeys.label(self.cfg["hotkey"]), style="Card.TLabel")
        self.hotkey_lbl.pack(side="right", padx=(0, 8))
        ttk.Label(card, text="Reads the selected text without clicking the bar. Pressing it again stops the read.",
                  style="Sub.Card.TLabel").pack(anchor="w", pady=(4, 0))

    def _record_hotkey(self):
        """Change…: the next key combination with a modifier becomes the shortcut; Esc keeps the old one."""
        self.hotkey_lbl["text"] = "Press keys…"
        self.win.focus_force()
        self.win.bind("<KeyPress>", self._hotkey_key)

    def _hotkey_key(self, event):
        if event.keysym == "Escape":
            self._set_hotkey(self.cfg["hotkey"])
        elif (key := KEYS.get(event.keycode)) and (
                spec := hotkeys.spec({m for m, bit in TK_MODS.items() if event.state & bit}, key)):
            self._set_hotkey(spec)
        return "break"

    def _set_hotkey(self, spec):
        self.win.unbind("<KeyPress>")
        self.hotkey_lbl["text"] = hotkeys.label(spec)
        if spec != self.cfg["hotkey"]:
            self._set("hotkey", spec)

