"""select-to-tts: select text anywhere, press ▶ on the floating button, hear it read aloud."""
import ctypes
import queue
import threading
import time
import tkinter as tk

import pystray
from PIL import Image, ImageDraw

from . import selection
from .codex_rt import CodexEngine
from .engines import Chain, EdgeEngine, SapiEngine
from .popup import Popup
from .trigger import SelectionTrigger


def icon_image():
    img = Image.new("RGBA", (64, 64))
    d = ImageDraw.Draw(img)
    d.polygon([(6, 24), (20, 24), (36, 10), (36, 54), (20, 40), (6, 40)], fill="#4f8ef7")
    for r in (10, 18):
        d.arc((40 - r, 32 - r, 40 + r, 32 + r), -50, 50, fill="#4f8ef7", width=5)
    return img


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.events, self.clipboard_fallback, self._seq = queue.Queue(), True, 0
        self.chain = Chain([CodexEngine(), EdgeEngine(), SapiEngine()])
        self.popup = Popup(self.root, self.play, self.chain.stop, self.chain.prepare)
        self.trigger = SelectionTrigger(self._selected, lambda x, y: self.events.put(("press", x, y)))
        self.icon = pystray.Icon("select-to-tts", icon_image(), "Select to TTS", self._menu())

    def _menu(self):
        def only(name, label):
            return pystray.MenuItem(label, lambda: setattr(self.chain, "only", name),
                                    checked=lambda _: self.chain.only == name, radio=True)
        return pystray.Menu(
            pystray.MenuItem(lambda _: f"Last engine: {self.chain.last or '-'}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            only(None, "Auto (Codex, then Edge, then Windows)"),
            only("Codex", "Codex only"), only("Edge", "Edge only"),
            only("Windows", "Windows only (offline)"),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Clipboard fallback", self._toggle_clipboard,
                             checked=lambda _: self.clipboard_fallback),
            pystray.MenuItem("Quit", lambda: self.events.put(("quit",))))

    def _toggle_clipboard(self):
        self.clipboard_fallback = not self.clipboard_fallback

    def _selected(self, x, y):  # mouse-hook thread: hand off, never block
        self._seq += 1
        threading.Thread(target=self._read, args=(self._seq, x, y), daemon=True).start()

    def _read(self, seq, x, y):
        time.sleep(0.08)  # let the app finish updating its selection
        try:
            text = selection.read(self.clipboard_fallback)
        except Exception:
            return  # some apps throw from UIA; no popup is the right outcome
        if text and seq == self._seq:
            self.events.put(("show", text, x, y))

    def play(self, text, lang_tag):
        self.chain.speak(text, lang_tag, lambda err: self.events.put(("done", err)))

    def _pump(self):
        while not self.events.empty():
            kind, *args = self.events.get_nowait()
            try:
                self._handle(kind, *args)
            except Exception as e:
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
        elif kind == "quit":
            self.trigger.stop()
            self.chain.close()
            self.icon.stop()
            self.root.destroy()

    def run(self):
        threading.Thread(target=self.icon.run, daemon=True).start()
        self.trigger.start()
        self.root.after(30, self._pump)
        self.root.mainloop()


def main():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "select-to-tts-single-instance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # tk and the mouse hook agree on pixels
    App().run()
    ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
