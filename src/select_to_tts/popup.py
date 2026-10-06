"""The small floating Play/Stop button with a language menu. Never takes focus from the source app.

One cohesive widget, so it stays in one file even though it passes 80 lines.
"""
import ctypes
import tkinter as tk
from ctypes import wintypes

from . import lang

GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x80, 0x8
IDLE_HIDE_MS = 4000
BG, FG, ACCENT, BORDER = "#202124", "#e8eaed", "#4f8ef7", "#5f6368"


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT),
                ("flags", wintypes.DWORD)]


def work_area(x, y) -> wintypes.RECT:
    """Usable area (minus taskbar) of the monitor under the point."""
    u32 = ctypes.windll.user32
    u32.MonitorFromPoint.restype = wintypes.HMONITOR
    u32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    info = _MonitorInfo(cb=ctypes.sizeof(_MonitorInfo))
    u32.GetMonitorInfoW(u32.MonitorFromPoint(wintypes.POINT(x, y), 2), ctypes.byref(info))
    return info.work


class Popup:
    def __init__(self, root, on_play, on_stop, on_lang):
        self.on_play, self.on_stop, self.on_lang = on_play, on_stop, on_lang
        self.text, self.playing, self.menu_open, self._hide_job = "", False, False, None
        self.lang = tk.StringVar(master=root, value="")  # "" means Auto
        w = self.win = tk.Toplevel(root, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        style = dict(bg=BG, fg=FG, activebackground="#3c4043", activeforeground=FG, bd=0,
                     font=("Segoe UI", 11), cursor="hand2")
        self.btn = tk.Button(w, text="▶", width=2, command=self._toggle, **{**style, "fg": ACCENT})
        self.btn.pack(side="left", padx=(4, 0), pady=2)
        self.menu_btn = tk.Menubutton(w, text="Auto ▾", direction="above", **style)
        menu = tk.Menu(self.menu_btn, tearoff=0, postcommand=self._menu_posted)
        for tag, label in [("", "Auto")] + [(t, v[0]) for t, v in lang.LANGS.items()]:
            menu.add_radiobutton(label=label, value=tag, variable=self.lang, command=self._lang_changed)
        self.menu_btn["menu"] = menu
        self.menu_btn.pack(side="left", padx=(0, 6), pady=2)
        w.bind("<Enter>", lambda _e: self._cancel_hide())
        w.bind("<Leave>", lambda _e: self._schedule_hide())
        w.withdraw()
        w.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(w.winfo_id())
        ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                            ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)

    def show(self, text, x, y):
        self.text, self.playing = text, False
        self.lang.set("")
        self.menu_btn["text"], self.btn["text"] = "Auto ▾", "▶"
        w = self.win
        w.update_idletasks()
        area, h = work_area(x, y), w.winfo_reqheight()
        top = y - h - 14 if y - h - 14 >= area.top else y + 16  # above: Windows' own text bar sits below
        w.geometry(f"+{min(x + 12, area.right - w.winfo_reqwidth())}+{min(top, area.bottom - h)}")
        w.deiconify()
        self._schedule_hide()

    def hide(self):
        self._cancel_hide()
        self.win.withdraw()
        self.on_stop()  # drops the Codex session warmed up for this popup

    @property
    def visible(self):
        return self.win.winfo_viewable()

    def contains(self, x, y):
        w = self.win
        return (self.visible and w.winfo_rootx() <= x < w.winfo_rootx() + w.winfo_width()
                and w.winfo_rooty() <= y < w.winfo_rooty() + w.winfo_height())

    def set_playing(self, playing):
        self.playing = playing
        self.btn["text"] = "■" if playing else "▶"
        if not playing:
            self._schedule_hide()

    def _toggle(self):
        if self.playing:
            self.on_stop()
            self.set_playing(False)
        else:
            self._cancel_hide()
            self.set_playing(True)
            self.on_play(self.text, self.lang.get() or None)

    def _lang_changed(self):
        tag = self.lang.get()
        self.menu_btn["text"] = f"{lang.name(tag) or 'Auto'} ▾"
        self.on_lang(tag or None)

    def _menu_posted(self):
        self.menu_open = True  # the next click belongs to the menu, not "outside the popup"
        self._cancel_hide()

    def _schedule_hide(self):
        self._cancel_hide()
        if not (self.playing or self.menu_open):
            self._hide_job = self.win.after(IDLE_HIDE_MS, self.hide)

    def _cancel_hide(self):
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None
