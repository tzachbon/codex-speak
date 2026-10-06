"""The small floating Play/Stop button with a language menu. Never takes focus from the source app.

One cohesive widget, so it stays in one file even though it passes 80 lines.
"""
import ctypes
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

from . import lang, settings

GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST = -20, 0x08000000, 0x80, 0x8
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
IDLE_HIDE_MS = 4000
# Windows 11 light flyout colors
BG, HOVER, PRESSED, FG, ACCENT, DIVIDER = "#f9f9f9", "#ededed", "#e4e4e4", "#1b1b1b", "#005fb8", "#e0e0e0"
PLAY, PAUSE, STOP, CHEVRON = "\ue768", "\ue769", "\ue71a", "\ue70d"


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
    def __init__(self, root, speed, *, on_play, on_stop, on_pause, on_resume, on_lang, on_speed):
        self.on_play, self.on_stop, self.on_pause, self.on_resume = on_play, on_stop, on_pause, on_resume
        self.on_lang, self.on_speed = on_lang, on_speed
        self.text, self.playing, self.paused, self.menu_open, self._hide_job = "", False, False, False, None
        self.lang = tk.StringVar(master=root, value="")  # "" means Auto
        self.speed = tk.DoubleVar(master=root, value=speed)
        icons, text = fonts(root)
        w = self.win = tk.Toplevel(root, bg=BG)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        self.btn = _FlatButton(w, self._toggle, (PLAY, (icons, 11), ACCENT))
        self.btn.pack(side="left", padx=("2p", 0), pady="2p")
        self.stop_btn = _FlatButton(w, self._stop, (STOP, (icons, 11), FG))  # packed while reading
        self.spinner = tk.Canvas(w, bg=BG, highlightthickness=0)  # shown until speech starts
        self._spin_angle, self.loading = 0, False
        self.divider = tk.Frame(w, bg=DIVIDER, width=1)
        self.divider.pack(side="left", fill="y", pady="5p", padx="2p")
        self.lang_btn = _FlatButton(w, lambda: self._post_menu(self.lang_btn, self.menu),
                                    ("Auto", (text, 10), FG),
                                    (CHEVRON, (icons, 7), FG))
        self.lang_btn.pack(side="left", padx=0, pady="2p")
        self.speed_btn = _FlatButton(w, lambda: self._post_menu(self.speed_btn, self.speed_menu),
                                     (settings.speed_label(speed), (text, 10), FG), (CHEVRON, (icons, 7), FG))
        self.speed_btn.pack(side="left", padx=(0, "2p"), pady="2p")
        self.menu = tk.Menu(w, tearoff=0, postcommand=self._menu_posted)
        for tag, label in [("", "Auto")] + [(t, v[0]) for t, v in lang.LANGS.items()]:
            self.menu.add_radiobutton(label=label, value=tag, variable=self.lang,
                                      command=self._lang_changed)
        self.speed_menu = tk.Menu(w, tearoff=0, postcommand=self._menu_posted)
        for preset in settings.SPEED_PRESETS:
            self.speed_menu.add_radiobutton(label=settings.speed_label(preset), value=preset,
                                            variable=self.speed, command=self._speed_changed)
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
        self.text = text
        self.set_playing(False)
        self.lang.set("")
        self.lang_btn.parts[1]["text"] = "Auto"
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

    def set_loading(self, loading):
        if loading == self.loading:
            return
        self.loading = loading
        if loading:
            b = self.btn
            self.spinner.configure(width=b.winfo_width(), height=b.winfo_height())
            self.spinner.pack(side="left", padx=("2p", 0), pady="2p", before=b)
            b.pack_forget()
            self._spin()
        else:
            self.btn.pack(side="left", padx=("2p", 0), pady="2p", before=self.spinner)
            self.spinner.pack_forget()

    def _spin(self):
        if not self.loading:
            return
        c, size = self.spinner, min(self.btn.winfo_width(), self.btn.winfo_height())
        x, y, r = int(c["width"]) / 2, int(c["height"]) / 2, size * 0.28
        c.delete("all")
        c.create_arc(x - r, y - r, x + r, y + r, start=self._spin_angle, extent=270, style="arc",
                     outline=ACCENT, width=max(2, round(size / 14)))
        self._spin_angle = (self._spin_angle - 24) % 360
        self.win.after(40, self._spin)

    def set_playing(self, playing, paused=False):
        self.playing, self.paused = playing, playing and paused
        if not playing:
            self.set_loading(False)
        self.btn.parts[1]["text"] = PAUSE if playing and not paused else PLAY
        if playing:
            self.stop_btn.pack(side="left", padx=0, pady="2p", before=self.divider)
        else:
            self.stop_btn.pack_forget()
            self._schedule_hide()

    def _toggle(self):
        if not self.playing:
            self._cancel_hide()
            self.set_playing(True)
            self.set_loading(True)
            self.on_play(self.text, self.lang.get() or None)
        elif self.paused:
            self.on_resume()
            self.set_playing(True)
        else:
            self.on_pause()
            self.set_playing(True, paused=True)

    def _stop(self):
        self.on_stop()
        self.set_playing(False)

    def _post_menu(self, button, menu):
        menu.update_idletasks()
        menu.post(button.winfo_rootx(), button.winfo_rooty() - menu.winfo_reqheight())  # upward

    def set_speed(self, speed):
        self.speed.set(speed)
        self.speed_btn.parts[1]["text"] = settings.speed_label(speed)

    def _speed_changed(self):
        self.set_speed(self.speed.get())
        self.on_speed(self.speed.get())

    def _lang_changed(self):
        tag = self.lang.get()
        self.lang_btn.parts[1]["text"] = lang.name(tag) or "Auto"
        self.on_lang(tag or None)

    def _menu_posted(self):
        self.menu_open = True  # the next click belongs to the menu, not "outside the popup"
        self._cancel_hide()

    def _schedule_hide(self):
        self._cancel_hide()
        if not (self.playing or self.menu_open) and self.visible:  # a hidden popup must not stop reads
            self._hide_job = self.win.after(IDLE_HIDE_MS, self.hide)

    def _cancel_hide(self):
        if self._hide_job:
            self.win.after_cancel(self._hide_job)
            self._hide_job = None
