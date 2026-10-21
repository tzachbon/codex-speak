"""The small pill shown after an in-place rewrite: a message, then Undo, Review, and Mode. Never takes focus."""
import tkinter as tk

from .captions import _get_parent, _get_style, _set_style
from .popup import (BG, CHEVRON, DIVIDER, FG, GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
                    _FlatButton, fonts, round_corners, work_area)

HIDE_MS = 6000
ACTIONS = ("undo", "review", "mode", "copy")

def floating(root, **options):
    """A borderless, topmost, rounded window that never activates, so the target app keeps focus and its caret."""
    w = tk.Toplevel(root, bg=BG, **options)
    w.overrideredirect(True)
    w.attributes("-topmost", True)
    w.withdraw()
    w.update_idletasks()
    hwnd = _get_parent(w.winfo_id())
    _set_style(hwnd, GWL_EXSTYLE, _get_style(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
    round_corners(hwnd)
    return w

def place(w, x, y):
    """Below the point, kept inside the work area of its monitor."""
    w.update_idletasks()
    area, width, height = work_area(x, y), w.winfo_reqwidth(), w.winfo_reqheight()
    top = y + 16 if y + 16 + height <= area.bottom else y - height - 14
    w.geometry(f"+{max(area.left, min(x - width // 2, area.right - width))}+{max(area.top, top)}")

class Toast:
    def __init__(self, root, on_action):
        """on_action(name) gets one of ACTIONS. The caller decides whether the toast stays."""
        self._hide_job = None
        self._hovered = False
        icons, text = self.fonts = fonts(root)
        w = self.win = floating(root)
        self.label = tk.Label(w, bg=BG, fg=FG, font=(text, 10), padx=0, pady=0)
        self.label.pack(side="left", padx=("8p", "4p"), pady="4p")
        self.divider = tk.Frame(w, bg=DIVIDER, width=1)
        self.divider.pack(side="left", fill="y", pady="5p", padx="2p")
        self.buttons = {}
        for name in ACTIONS:
            parts = [(name.title(), (text, 10), FG)] + ([(CHEVRON, (icons, 7), FG)] if name == "mode" else [])
            self.buttons[name] = _FlatButton(w, lambda name=name: on_action(name), *parts)
        w.bind("<Enter>", self._enter)
        w.bind("<Leave>", self._leave)

    def show(self, message, actions=("undo", "review", "mode"), x=None, y=None):
        """Near (x, y), or the mouse pointer when not given. Replaces whatever the toast showed before."""
        self.label["text"] = message
        for button in self.buttons.values():
            button.pack_forget()
        for name in actions:
            self.buttons[name].pack(side="left", padx=(0, "2p"), pady="2p")
        if actions:
            self.divider.pack(side="left", fill="y", pady="5p", padx="2p", before=self.buttons[actions[0]])
        else:
            self.divider.pack_forget()
        if x is None or y is None:
            x, y = self.win.winfo_pointerxy()
        place(self.win, x, y)
        self.win.deiconify()
        self._schedule_hide()

    def hide(self):
        self._cancel_hide()
        self._hovered = False
        self.win.withdraw()

    def destroy(self):
        self._cancel_hide()
        self.win.destroy()

    @property
    def visible(self):
        return bool(self.win.winfo_exists() and self.win.winfo_viewable())

    def contains(self, x, y):
        w = self.win
        return (self.visible and w.winfo_rootx() <= x < w.winfo_rootx() + w.winfo_width()
                and w.winfo_rooty() <= y < w.winfo_rooty() + w.winfo_height())

    def _schedule_hide(self):
        self._cancel_hide()
        if not self._hovered:
            self._hide_job = self.win.after(HIDE_MS, self.hide)

    def _enter(self, _event):
        self._hovered = True
        self._cancel_hide()

    def _leave(self, _event):
        self._hovered = False
        self._schedule_hide()

    def _cancel_hide(self):
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None
