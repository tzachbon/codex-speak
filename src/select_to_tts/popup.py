"""The small floating Play/Stop button with a language menu. Never takes focus from the source app.

One cohesive widget, so it stays in one file even though it passes 80 lines.
"""
import ctypes
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

from . import lang

GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x80, 0x8
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
IDLE_HIDE_MS = 4000
# Windows 11 light flyout colors
BG, HOVER, PRESSED, FG, ACCENT, DIVIDER = "#f9f9f9", "#ededed", "#e4e4e4", "#1b1b1b", "#005fb8", "#e0e0e0"
PLAY, STOP, CHEVRON = "", "", ""


def fonts(root):
    """Windows 11 fonts, with the Windows 10 equivalents as fallback."""
    have = set(tkfont.families(root))
    icons = "Segoe Fluent Icons" if "Segoe Fluent Icons" in have else "Segoe MDL2 Assets"
    text = "Segoe UI Variable Text" if "Segoe UI Variable Text" in have else "Segoe UI"
    return icons, text


def round_corners(hwnd):
    corner = ctypes.c_int(DWMWCP_ROUND)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                               ctypes.byref(corner), ctypes.sizeof(corner))


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


class _FlatButton(tk.Frame):
    """A borderless button made of labels, with Windows 11 hover and pressed fills."""

    def __init__(self, master, command, *labels):
        super().__init__(master, bg=BG, cursor="hand2")
        self.command, self.parts = command, [self]
        for text, font, fg in labels:
            lbl = tk.Label(self, text=text, font=font, fg=fg, bg=BG, padx=0, pady=0)
            lbl.pack(side="left", padx=("3p" if len(self.parts) == 1 else 0, "3p"), pady="3p")
            self.parts.append(lbl)
        for w in self.parts:
            w.bind("<Enter>", lambda _e: self._fill(HOVER))
            w.bind("<Leave>", lambda _e: self._fill(BG))
            w.bind("<ButtonPress-1>", lambda _e: self._fill(PRESSED))
            w.bind("<ButtonRelease-1>", self._release)

    def _fill(self, color):
        for w in self.parts:
            w["bg"] = color

    def _release(self, e):
        self._fill(HOVER)
        if self.winfo_containing(e.x_root, e.y_root) in self.parts:
            self.command()


class Popup:
    def __init__(self, root, on_play, on_stop, on_lang):
        self.on_play, self.on_stop, self.on_lang = on_play, on_stop, on_lang
        self.text, self.playing, self.menu_open, self._hide_job = "", False, False, None
        self.lang = tk.StringVar(master=root, value="")  # "" means Auto
        icons, text = fonts(root)
        w = self.win = tk.Toplevel(root, bg=BG)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        self.btn = _FlatButton(w, self._toggle, (PLAY, (icons, 11), ACCENT))
        self.btn.pack(side="left", padx=("2p", 0), pady="2p")
        tk.Frame(w, bg=DIVIDER, width=1).pack(side="left", fill="y", pady="5p", padx="2p")
        self.lang_btn = _FlatButton(w, self._post_menu, ("Auto", (text, 10), FG),
                                    (CHEVRON, (icons, 7), FG))
        self.lang_btn.pack(side="left", padx=(0, "2p"), pady="2p")
        self.menu = tk.Menu(w, tearoff=0, postcommand=self._menu_posted)
        for tag, label in [("", "Auto")] + [(t, v[0]) for t, v in lang.LANGS.items()]:
            self.menu.add_radiobutton(label=label, value=tag, variable=self.lang,
                                      command=self._lang_changed)
        w.bind("<Enter>", lambda _e: self._cancel_hide())
        w.bind("<Leave>", lambda _e: self._schedule_hide())
        w.withdraw()
        w.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(w.winfo_id())
        ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                            ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        round_corners(hwnd)

    def show(self, text, x, y):
        self.text, self.playing = text, False
        self.lang.set("")
        self.lang_btn.parts[1]["text"], self.btn.parts[1]["text"] = "Auto", PLAY
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
        self.btn.parts[1]["text"] = STOP if playing else PLAY
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

    def _post_menu(self):
        b = self.lang_btn
        self.menu.update_idletasks()
        self.menu.post(b.winfo_rootx(), b.winfo_rooty() - self.menu.winfo_reqheight())  # upward

    def _lang_changed(self):
        tag = self.lang.get()
        self.lang_btn.parts[1]["text"] = lang.name(tag) or "Auto"
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
