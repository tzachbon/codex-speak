"""select-to-tts: select text anywhere, press ▶ on the floating button, hear it read aloud."""
import ctypes
import logging
import logging.handlers
import os
import queue
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes

import pystray
from PIL import Image, ImageDraw

from . import lang, selection, sentences, settings, stt_server
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
        self.events, self._seq, self.settings_win, self._read_id = queue.Queue(), 0, None, 0
        self._units, self._unit_index, self._pending_next, self._read_options = [], 0, False, None
        self.stt, self.stt_error = None, None
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
        self.popup = Popup(self.root, self.cfg["speed"], on_play=self.play, on_stop=self.stop,
                           on_pause=self.pause, on_resume=self.resume,
                           on_lang=self._prepare_selection, on_speed=self._popup_speed)
        self._configure_captions()
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
        if key.startswith("caption_"):
            if hasattr(self, "popup"):
                self._configure_captions()
            return
        if self._read_options and key in ("engine", "speed", "prefetch"):
            return  # speech options are captured for the entire selection
        if key == "engine":
            self.chain.only = value
        elif key == "speed":
            for e in self.chain.engines:
                e.speed = value
        elif key == "prefetch":
            self.chain.prefetch = value
        elif key == "stt_server":
            self._run_stt(value)

    def _configure_captions(self):
        self.popup.configure_captions(self.cfg["caption_font_size"], self.cfg["caption_background"],
                                      self.cfg["caption_background_opacity"])

    def _run_stt(self, on, tries=60):
        if on and not self.stt:
            try:
                self.stt, self.stt_error = stt_server.start(), None
            except OSError as e:
                # The port stays taken while an earlier server finishes a transcription, or another
                # program uses it. Retry for 2 minutes, then show the error in Settings.
                self.stt_error = f"Could not start the server: {e.strerror or e}"
                if tries == 60:
                    log.warning("speech-to-text server did not start: %s", e)
                if tries:
                    self.root.after(2000, lambda: self.cfg["stt_server"] and self._run_stt(True, tries - 1))
        elif not on:
            self.stt_error = "The server is off."
            if self.stt:
                server, self.stt = self.stt, None
                server.shutdown()  # up to 0.5 s
                server.socket.close()  # frees the port now for a quick re-enable
                # server_close() waits for a transcription in flight, so not on the Tk thread
                threading.Thread(target=server.server_close, daemon=True).start()

    def change(self, key, value, save=True):
        self.cfg[key] = value
        self.apply(key, value)
        if key == "speed":  # keep the popup and an open Settings window showing the same speed
            self.popup.set_speed(value)
            if self.settings_win and self.settings_win.alive:
                self.settings_win.set_speed(value)
        if key in ("engine", "speed", "prefetch") and not self._read_options and self.popup.text:
            self._prepare_selection(self.popup.lang.get() or None)
        if not save:
            return
        try:
            settings.save(self.cfg)
        except OSError as e:
            self.icon.notify(f"Could not save settings: {e}", "Select to TTS")

    def _popup_speed(self, speed):
        self.change("speed", speed)

    def _prepare_selection(self, tag=None):
        if self._read_options or not self.popup.visible:
            return
        units = sentences.split(self.popup.text)
        if units:
            self.chain.prepare(tag, units[0], fallback_tag=lang.detect(self.popup.text))

    def test_voice(self, text):
        self.stop()  # a popup read in progress is replaced by the test
        if self.popup.visible:
            self.popup.hide()
        self._read_id += 1
        rid = self._read_id
        done, _ = self._logged(text, lambda err: self.events.put(("done", err, rid)))
        self.chain.speak(text, "en-US", done)

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
        if self._read_options:
            self.stop()
        self._read_id += 1
        rid = self._read_id  # events from an older read are ignored when they arrive late
        self._units, self._unit_index, self._pending_next = sentences.split(text), 0, False
        self._read_options = (lang_tag, self.cfg["engine"], self.cfg["speed"], lang.detect(text))
        self._read_done, self._read_heard = self._logged(text, lambda err: self.events.put(("done", err, rid)))
        self.popup.set_caption("")
        if self._units:
            self._start_unit()
        else:
            self._read_done(None)

    def _start_unit(self):
        rid, index = self._read_id, self._unit_index
        heard = self._read_heard
        self.chain.speak(self._units[index], self._read_options[0],
                         lambda err: self.events.put(("sentence_done", err, rid, index)),
                         lambda: (heard(), self.events.put(("audio", rid, index))),
                         fallback_tag=self._read_options[3])

    def _restore_speech_options(self):
        self._read_options = None
        for key in ("engine", "speed", "prefetch"):
            self.apply(key, self.cfg[key])

    def stop(self):
        self._read_id += 1  # invalidate callbacks before asynchronous engine cleanup
        self._units, self._pending_next = [], False
        self.chain.stop()
        self._restore_speech_options()
        self.popup.set_playing(False)

    def pause(self):
        self.popup.set_caption_paused(True)
        self.chain.pause()

    def resume(self):
        self.popup.set_caption_paused(False)
        self.chain.resume()
        if self._pending_next:
            self._pending_next = False
            self._start_unit()

    def _logged(self, text, on_done):
        """(done, heard): done logs the read, heard marks the first audio, which ends the spinner."""
        t0, first, speed = time.monotonic(), [], self.cfg["speed"]

        def done(err):  # never the text, nor an error message, which could echo the text
            error = f"{type(err).__name__} from {type(err.__cause__).__name__}" if err else None
            log.info("read %d chars with %s in %.1fs (first audio %s) at %sx, error: %s", len(text),
                     self.chain.last, time.monotonic() - t0, f"{first[0]:.1f}s" if first else "-",
                     speed, error)
            on_done(err)
        return done, lambda: first or first.append(time.monotonic() - t0)

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
            # double-clicking the popup is not a new selection, and a running read isn't interrupted
            if not (p.contains(x, y) or (p.playing and not p.paused)):
                if p.paused:
                    self.stop()  # a new selection replaces the paused read
                p.show(text, x, y)
                self._prepare_selection()
        elif kind == "press":
            if p.contains(*args):
                pass  # clicks on the popup itself (including opening the menu)
            elif p.menu_open:
                p.menu_open = False  # this click picked a language or dismissed the menu
                p._schedule_hide()
            elif p.visible and not p.playing:
                p.hide()
        elif kind == "audio":
            if args[0] == self._read_id and args[1] == self._unit_index and self._read_options:
                p.set_loading(False)
                p.set_caption(self._units[self._unit_index])
        elif kind == "sentence_done":
            err, rid, index = args
            if rid != self._read_id or index != self._unit_index or not self._read_options:
                return
            if err or index + 1 == len(self._units):
                self._unit_index += 1
                self._read_done(err)
            else:
                self.chain.only = self.chain.last  # preserve the first successful voice across the selection
                self._unit_index += 1
                if p.paused:
                    self._pending_next = True
                else:
                    self._start_unit()
        elif kind == "done":
            if args[1] != self._read_id:
                return
            self.stop()
            if args[0]:
                self.icon.notify(f"Could not read aloud: {args[0]}", "Select to TTS")
        elif kind == "settings":
            if self.settings_win and self.settings_win.alive:
                self.settings_win.focus()
            else:
                self.settings_win = SettingsWindow(self.root, dict(self.cfg), icon_image(256), self.change,
                                                   self.test_voice, lambda: self.stt_error)
        elif kind == "quit":
            self.stop()
            self._run_stt(False)
            self.trigger.stop()
            self.chain.close()
            self.icon.stop()
            self.root.destroy()

    def _wait_show_settings(self):
        while k32.WaitForSingleObject(self.show_event, 0xFFFFFFFF) == 0:
            self.events.put(("settings",))

    def run(self):
        threading.Thread(target=self.icon.run, daemon=True).start()
        threading.Thread(target=self._wait_show_settings, daemon=True).start()
        self.trigger.start()
        self.root.after(30, self._pump)
        self.root.mainloop()


def main():
    if sys.argv[1:2] == ["--startup"]:  # used by the installer: SelectToTTS.exe --startup on|off|refresh
        try:
            if sys.argv[2:3] == ["refresh"]:
                settings.refresh_startup()
            else:
                settings.set_startup(sys.argv[2:3] == ["on"])
        except Exception:
            sys.exit(1)  # a windowed exe would show a dialog that blocks setup; the user can retry in Settings
        return
    mutex = k32.CreateMutexW(None, False, "select-to-tts-single-instance")
    if k32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS: ask the running copy to open Settings
        for _ in range(50):  # the running copy may still be starting up
            ev = k32.OpenEventW(0x0002, False, SHOW_SETTINGS)  # EVENT_MODIFY_STATE
            if ev:
                k32.SetEvent(ev)
                k32.CloseHandle(ev)
                break
            time.sleep(0.1)
        return
    show_event = k32.CreateEventW(None, False, False, SHOW_SETTINGS)  # before the slow start-up
    os.makedirs(settings.DIR, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(os.path.join(settings.DIR, "select-to-tts.log"),
                                                   maxBytes=256_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler],  # libraries log IPs at INFO
                        format="%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # tk and the mouse hook agree on pixels
    log.info("start, launch command %s", settings.launch_command())
    try:
        settings.refresh_startup()
    except OSError:
        log.exception("could not update the sign-in task")
    try:
        app = App()
        app.show_event = show_event
        app.run()
    except Exception:
        log.exception("crashed")
        raise
    k32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
