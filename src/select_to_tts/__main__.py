"""select-to-tts: select text anywhere, press ▶ on the floating button, hear it read aloud."""
import ctypes
import logging
import logging.handlers
import os
import queue
import threading
import time
import tkinter as tk
from ctypes import wintypes

import pystray
from PIL import Image, ImageDraw

from . import selection, settings
from .codex_rt import CodexEngine
from .engines import Chain, EdgeEngine, SapiEngine
from .popup import Popup
from .settings_ui import SettingsWindow
from .trigger import SelectionTrigger

log = logging.getLogger("select_to_tts")
k32 = ctypes.windll.kernel32
for _f in (k32.CreateMutexW, k32.CreateEventW, k32.OpenEventW):
    _f.restype = wintypes.HANDLE
SHOW_SETTINGS = "select-to-tts-show-settings"  # a second launch sets this to open Settings


def icon_image(size=64):
    """Speaker on a Windows-blue rounded square, drawn 4x larger and scaled down for smooth edges."""
    k = size * 4 / 64
    img = Image.new("RGBA", (size * 4, size * 4))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size * 4 - 1, size * 4 - 1), radius=14 * k, fill="#005fb8")
    d.polygon([(p[0] * k, p[1] * k) for p in [(12, 26), (22, 26), (34, 15), (34, 49), (22, 38), (12, 38)]],
              fill="white")
    for r in (8, 15):
        d.arc(((37 - r) * k, (32 - r) * k, (37 + r) * k, (32 + r) * k), -50, 50, fill="white",
              width=round(4 * k))
    return img.resize((size, size), Image.LANCZOS)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.events, self._seq, self.settings_win = queue.Queue(), 0, None
        self.chain = Chain([CodexEngine(), EdgeEngine(), SapiEngine()])
        first_run = not os.path.exists(settings.PATH)
        self.cfg = settings.load()
        if first_run:
            try:
                settings.save(self.cfg)
            except OSError:
                pass  # Settings just shows again on the next start
            self.events.put(("settings",))  # show new users where the app lives
        for key, value in self.cfg.items():
            self.apply(key, value)
        self.popup = Popup(self.root, self.play, self.chain.stop, self.chain.prepare)
        self.trigger = SelectionTrigger(self._selected, lambda x, y: self.events.put(("press", x, y)))
        self.icon = pystray.Icon("select-to-tts", icon_image(), "Select to TTS", self._menu())

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem("Settings", lambda: self.events.put(("settings",)), default=True),
            pystray.MenuItem(lambda _: f"Last engine: {self.chain.last or '-'}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self.events.put(("quit",))))

    def apply(self, key, value):
        """Called on the tk thread. Engines read these attributes when the next read starts."""
        if key == "engine":
            self.chain.only = value
        elif key == "speed":
            for e in self.chain.engines:
                e.speed = value

    def change(self, key, value):
        self.cfg[key] = value
        self.apply(key, value)
        try:
            settings.save(self.cfg)
        except OSError as e:
            self.icon.notify(f"Could not save settings: {e}", "Select to TTS")

    def test_voice(self, text):
        self.popup.set_playing(False)  # a popup read in progress is replaced by the test
        self.chain.speak(text, "en-US", self._logged(text, lambda err: err and self.events.put(("done", err))))

    def _selected(self, x, y):  # mouse-hook thread: hand off, never block
        self._seq += 1
        threading.Thread(target=self._read, args=(self._seq, x, y), daemon=True).start()

    def _read(self, seq, x, y):
        time.sleep(0.08)  # let the app finish updating its selection
        try:
            text = selection.read(self.cfg["clipboard_fallback"])
        except Exception:
            return  # some apps throw from UIA; no popup is the right outcome
        if text and seq == self._seq:
            self.events.put(("show", text, x, y))

    def play(self, text, lang_tag):
        self.chain.speak(text, lang_tag, self._logged(text, lambda err: self.events.put(("done", err))))

    def _logged(self, text, on_done):
        t0 = time.monotonic()

        def done(err):  # the text itself is never logged
            log.info("read %d chars with %s in %.1fs at %sx, error: %r", len(text), self.chain.last,
                     time.monotonic() - t0, self.cfg["speed"], err)
            on_done(err)
        return done

    def _pump(self):
        while not self.events.empty():
            kind, *args = self.events.get_nowait()
            try:
                self._handle(kind, *args)
            except Exception as e:
                log.exception("handling %s", kind)
                self.icon.notify(f"Unexpected error: {e}", "Select to TTS")
            if kind == "quit":
                return
        self.root.after(30, self._pump)

    def _handle(self, kind, *args):
        p = self.popup
        if kind == "show":
            text, x, y = args
            if not (p.contains(x, y) or p.playing):  # double-clicking ▶ is not a new selection
                p.show(text, x, y)
                self.chain.prepare(None)  # warm up Codex while the mouse travels to ▶
        elif kind == "press":
            if p.contains(*args):
                pass  # clicks on the popup itself (including opening the menu)
            elif p.menu_open:
                p.menu_open = False  # this click picked a language or dismissed the menu
                p._schedule_hide()
            elif p.visible and not p.playing:
                p.hide()
        elif kind == "done":
            p.set_playing(False)
            if args[0]:
                self.icon.notify(f"Could not read aloud: {args[0]}", "Select to TTS")
        elif kind == "settings":
            if self.settings_win and self.settings_win.alive:
                self.settings_win.focus()
            else:
                self.settings_win = SettingsWindow(self.root, dict(self.cfg), icon_image(256), self.change,
                                                   self.test_voice)
        elif kind == "quit":
            self.trigger.stop()
            self.chain.close()
            self.icon.stop()
            self.root.destroy()

    def _wait_show_settings(self):
        ev = k32.CreateEventW(None, False, False, SHOW_SETTINGS)
        while k32.WaitForSingleObject(ev, 0xFFFFFFFF) == 0:
            self.events.put(("settings",))

    def run(self):
        threading.Thread(target=self.icon.run, daemon=True).start()
        threading.Thread(target=self._wait_show_settings, daemon=True).start()
        self.trigger.start()
        self.root.after(30, self._pump)
        self.root.mainloop()


def main():
    mutex = k32.CreateMutexW(None, False, "select-to-tts-single-instance")
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS: ask the running copy to open Settings
        ev = k32.OpenEventW(0x0002, False, SHOW_SETTINGS)  # EVENT_MODIFY_STATE
        if ev:
            k32.SetEvent(ev)
            k32.CloseHandle(ev)
        return
    os.makedirs(settings.DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(settings.DIR, "select-to-tts.log"),
                                                   maxBytes=256_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler],  # libraries log IPs at INFO
                        format="%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # tk and the mouse hook agree on pixels
    log.info("start, launch command %s", settings.launch_command())
    try:
        App().run()
    except Exception:
        log.exception("crashed")
        raise
    k32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
