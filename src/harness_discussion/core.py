"""The platform-neutral app: reads selections aloud sentence by sentence, owns settings, updates and STT.

A host (win.host.TkHost or mac.host.MacHost) owns the main thread, windows, tray or menu bar,
and the OS services. Background threads only put events on `App.events`; the host drains it
on the main thread through `pump`.
"""
import logging
import os
import queue
import shutil
import sys
import threading
import time

from . import lang, sentences, settings, stt_server, updates

log = logging.getLogger("harness_discussion")
# Codex's transcript arrives about 0.4 s before its audio, which then waits in the 0.25 s jitter cushion.
CAPTION_DELAY_S = 0.6
SPEECH_KEYS = ("sources", "voices", "speed", "prefetch")  # captured for the entire selection


class App:
    def __init__(self, host):
        self.host = host
        host.app = self
        self.events, self._seq, self.settings_win, self._read_id = queue.Queue(), 0, None, 0
        self._units, self._unit_index, self._pending_next, self._read_options = [], 0, False, None
        self._continuous, self._last_caption, self._held_caption = False, "", ""
        self.stt, self.stt_error = None, None
        self._draining_stt = []
        self._closing, self._update_busy, self._update_manual = False, False, False
        self._pending_update, self.update_version = None, None
        self._update_text = ("Checks at startup and daily when enabled." if sys.platform == "darwin"
                             else "Checks at startup and daily when enabled. Updates restart this app.")
        from .engines import Chain
        self.chain = Chain(host.engines())
        self.chain.on_engine = lambda name: self.events.put(("engine", name))
        self.statuses = {}  # engine name -> status(), filled by refresh_statuses
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
        self.popup = host.make_popup(self.cfg["speed"], on_play=self.play, on_stop=self.stop,
                                     on_pause=self.pause, on_resume=self.resume,
                                     on_lang=self._prepare_selection, on_speed=self._popup_speed,
                                     on_settings=lambda: self.events.put(("settings",)))
        self._configure_captions()

    def start(self):
        """Starts listening for selections and schedules the update check."""
        self.host.start_trigger(self._selected, lambda x, y: self.events.put(("press", x, y)))
        self.host.after(30_000, self._auto_update)
        self.refresh_statuses()

    def refresh_statuses(self):
        """Settings shows the cached result: status() can take seconds, as macOS asks a login shell for codex."""
        def work():
            statuses = {}
            for e in self.chain.engines:
                try:
                    statuses[e.name] = e.status() if hasattr(e, "status") else "ready"
                except Exception as err:
                    log.warning("%s status failed: %s", e.name, type(err).__name__)
                    statuses[e.name] = "missing"
            self.statuses = statuses
            self.events.put(("statuses",))
        threading.Thread(target=work, daemon=True).start()

    def apply(self, key, value):
        """Called on the main thread. Engines read these attributes when the next read starts."""
        if key.startswith("caption_"):
            if hasattr(self, "popup"):
                self._configure_captions()
            return
        if self._read_options and key in SPEECH_KEYS:
            return  # speech options are captured for the entire selection
        if key == "sources":
            self.chain.enabled = [name for name, on in value if on]
            self.chain.only = None  # also ends the pin on the voice that read the selection's first sentence
        elif key == "voices":
            for e in self.chain.engines:
                if hasattr(e, "voices"):  # an unknown id reads with the engine's default
                    e.voice = value.get(e.name) if value.get(e.name) in dict(e.voices) else None
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
                    self.host.after(2000, lambda: self.cfg["stt_server"] and self._run_stt(True, tries - 1))
        elif not on:
            self.stt_error = "The server is off."
            if self.stt:
                server, self.stt = self.stt, None
                self._draining_stt.append(server)
                server.shutdown()  # up to 0.5 s
                server.socket.close()  # frees the port now for a quick re-enable
                # server_close() waits for a transcription in flight, so not on the main thread
                def close():
                    server.server_close()
                    self.events.put(("stt_closed", server))
                threading.Thread(target=close, daemon=True).start()

    def change(self, key, value, save=True):
        self.cfg[key] = value
        self.apply(key, value)
        if key == "speed":  # keep the popup and an open Settings window showing the same speed
            self.popup.set_speed(value)
            if self.settings_win and self.settings_win.alive:
                self.settings_win.set_speed(value)
        if key == "sources" and self.settings_win and self.settings_win.alive:
            self.settings_win.set_sources(value)
        if key in SPEECH_KEYS and not self._read_options and self.popup.text:
            self._prepare_selection(self.popup.lang_tag())
        if not save:
            return
        try:
            settings.save(self.cfg)
        except OSError as e:
            self.host.notify(f"Could not save settings: {e}")
        if key == "auto_update":
            if value:
                self.check_update(manual=False)
            elif not self._update_manual:
                self._discard_update()

    def update_state(self):
        return self._update_text, self._update_busy or self._pending_update is not None

    def available_version(self):
        """macOS only: the newer release found by the last check, or None."""
        return self.update_version

    def _update_status(self, text):
        self._update_text = text
        if self.settings_win and self.settings_win.alive:
            self.settings_win.refresh_updates()

    def check_update(self, manual=True):
        if (not getattr(sys, "frozen", False) or self._closing or self._update_busy
                or self._pending_update is not None):
            return
        self._update_busy, self._update_manual = True, manual
        self._update_status("Checking for updates…")

        if sys.platform == "darwin":  # no in-app install: Settings links to the release page
            def work():
                try:
                    asset = updates.check()
                    version = asset["version"] if asset else None
                    text = f"v{version} is available." if asset else "You are up to date."
                except Exception as e:
                    version, text = None, f"Could not check for updates: {e}"
                self.events.put(("update_available", version, text))
        else:
            def work():
                try:
                    asset = updates.check()
                    if asset:
                        self.events.put(("update_status", f"Downloading v{asset['version']}…"))
                        path = updates.download(asset)
                        text = f"v{asset['version']} is ready to install."
                    else:
                        path, text = None, "You are up to date."
                except Exception as e:
                    path, text = None, f"Could not update: {e}"
                self.events.put(("update_result", path, text))
        threading.Thread(target=work, daemon=True).start()

    def _auto_update(self):
        if self.cfg["auto_update"]:
            self.check_update(manual=False)
        self.host.after(24 * 60 * 60 * 1000, self._auto_update)

    def _discard_update(self):
        if self._pending_update:
            shutil.rmtree(self._pending_update.parent, ignore_errors=True)
            self._pending_update = None
            self._update_status("Automatic update cancelled.")

    def _try_update(self):
        if not self._pending_update or self._closing:
            return
        if not self._update_manual and not self.cfg["auto_update"]:
            self._discard_update()
            return
        server = self.stt
        if (self._read_options or self.chain.busy or self._draining_stt
                or (server and not server.busy.acquire(blocking=False))):
            self._update_status("Update ready. Waiting for speech and transcription to finish…")
            self.host.after(1000, self._try_update)
            return
        try:
            settings.save(self.cfg)
            updates.install(self._pending_update)
        except Exception as e:
            if server:
                server.busy.release()
            self._discard_update()
            self._update_status(f"Could not install update: {e}")
            return
        self._handle("quit")

    def _popup_speed(self, speed):
        self.change("speed", speed)

    def _prepare_selection(self, tag=None):
        if self._read_options or not self.popup.visible:
            return
        units = self._units_for(self.popup.text)
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

    def _selected(self, x, y):  # trigger thread: hand off, never block
        self._seq += 1
        threading.Thread(target=self._read, args=(self._seq, x, y), daemon=True).start()

    def _read(self, seq, x, y):
        time.sleep(0.08)  # let the app finish updating its selection
        try:
            text = self.host.read_selection(self.cfg["clipboard_fallback"])
        except Exception:
            return  # some apps throw from the accessibility API; no popup is the right outcome
        if text and seq == self._seq:
            self.events.put(("show", text, x, y))

    def _units_for(self, text):
        """Codex reads the whole selection in one session; other engines go sentence by sentence."""
        if self.chain.continuous():
            return [text.strip()] if text.strip() else []
        return sentences.split(text)

    def play(self, text, lang_tag, only=None):
        """only: read through that engine alone, as a Settings Test button does."""
        if self._read_options:
            self.stop()
        self.chain.only = only  # after stop(), which clears it
        self._read_id += 1
        rid = self._read_id  # events from an older read are ignored when they arrive late
        self._continuous = self.chain.continuous()
        self._units, self._unit_index, self._pending_next = self._units_for(text), 0, False
        self._last_caption = self._held_caption = ""
        self._read_options = (lang_tag, self.cfg["sources"], self.cfg["speed"], lang.detect(text))
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
                         fallback_tag=self._read_options[3],
                         on_caption=lambda text: self.events.put(("caption", rid, index, text)))

    def _restore_speech_options(self):
        self._read_options = None
        for key in SPEECH_KEYS:
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
        held, self._held_caption = self._held_caption, ""
        if held:
            self._show_caption(held)
        self.chain.resume()
        if self._pending_next:
            self._pending_next = False
            self._start_unit()

    def _caption(self, rid, index, transcript):
        """Shows the sentence Codex is speaking, held while paused because the transcript keeps arriving."""
        if rid != self._read_id or index != self._unit_index or not self._read_options:
            return
        if self.popup.paused:
            self._held_caption = sentences.current(transcript)
        else:
            self._show_caption(sentences.current(transcript))

    def _show_caption(self, text):
        if text != self._last_caption:
            self._last_caption = text
            self.popup.set_caption(text)

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

    def pump(self):
        """Main thread, every 30 ms: handles what background threads queued."""
        while not self.events.empty():
            kind, *args = self.events.get_nowait()
            try:
                self._handle(kind, *args)
            except Exception as e:
                log.exception("handling %s", kind)
                self.host.notify(f"Unexpected error: {e}")
            if self._closing:
                return

    def _handle(self, kind, *args):
        p = self.popup
        if kind == "stt_closed":
            self._draining_stt.remove(args[0])
        elif kind == "update_status":
            self._update_status(args[0])
        elif kind == "update_available":
            self._update_busy = False
            self.update_version = args[0]
            self._update_status(args[1])
        elif kind == "update_result":
            self._update_busy = False
            self._pending_update = args[0]
            self._update_status(args[1])
            self._try_update()
        elif kind == "show":
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
                p.schedule_hide()
            elif p.visible and not p.playing:
                p.hide()
        elif kind == "audio":
            if args[0] == self._read_id and args[1] == self._unit_index and self._read_options:
                p.set_loading(False)
                if not self._continuous or self.chain.active_name != "Codex":
                    p.set_caption(self._units[self._unit_index])  # Codex captions follow its transcript
        elif kind == "caption":
            self.host.after(int(CAPTION_DELAY_S * 1000), lambda: self._caption(*args))
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
                self.host.notify(f"Could not read aloud: {args[0]}")
        elif kind == "settings":
            if self.settings_win and self.settings_win.alive:
                self.settings_win.focus()
            else:
                self.settings_win = self.host.open_settings()
            self.refresh_statuses()
        elif kind == "statuses":
            if self.settings_win and self.settings_win.alive:
                self.settings_win.refresh_sources()
        elif kind == "quit":
            self._closing = True
            self.stop()
            self._run_stt(False)
            self.host.stop_trigger()
            self.chain.close()
            self.host.quit()
