"""Windows host: Tk on the main thread, pystray in the tray, UI Automation for the selection."""
import threading
import tkinter as tk

import pystray

from ..codex_rt import CodexEngine
from ..cursor_tts import CursorEngine
from ..engines import EdgeEngine
from ..icons import icon_image
from . import selection
from .popup import Popup
from .settings_ui import SettingsWindow
from .trigger import SelectionTrigger
from .voice import SapiEngine


class TkHost:
    def __init__(self):
        self.app = None  # set by core.App
        self.root = tk.Tk()
        self.root.withdraw()
        self.trigger = None
        self.icon = pystray.Icon("harness-discussion", icon_image(), "Harness Discussion", self._menu())

    def _menu(self):
        put = lambda *event: lambda: self.app.events.put(event)
        return pystray.Menu(
            pystray.MenuItem("Settings", put("settings"), default=True),
            pystray.MenuItem(lambda _: f"Last voice source: {self.app.chain.last or '-'}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", put("quit")))

    def engines(self):
        return [CursorEngine(), CodexEngine(), EdgeEngine(), SapiEngine()]

    def make_popup(self, speed, **callbacks):
        return Popup(self.root, speed, **callbacks)

    def open_settings(self):
        a = self.app
        return SettingsWindow(self.root, dict(a.cfg), icon_image(256), a.change, a.test_voice,
                              lambda: a.stt_error, a.update_state, a.check_update, engines=a.chain.engines,
                              statuses=lambda: a.statuses,
                              on_play=lambda name: a.play(f"This is {name}.", None, only=name))

    def read_selection(self, clipboard_fallback):
        return selection.read(clipboard_fallback)

    def start_trigger(self, on_selection, on_press):
        self.trigger = SelectionTrigger(on_selection, on_press)
        self.trigger.start()

    def stop_trigger(self):
        if self.trigger:
            self.trigger.stop()

    def after(self, ms, fn):
        self.root.after(ms, fn)

    def notify(self, message):
        self.icon.notify(message, "Harness Discussion")

    def run(self, pump):
        def tick():
            pump()
            if not self.app._closing:
                self.root.after(30, tick)
        threading.Thread(target=self.icon.run, daemon=True).start()
        self.root.after(30, tick)
        self.root.mainloop()

    def quit(self):
        self.icon.stop()
        self.root.destroy()
