"""The shared core on a fake host: the read loop, fallback, and the macOS update check."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_speak import core, settings, updates
from codex_speak.audio import NoAudioError


class Engine:
    speed = 1.0

    def __init__(self, name, fail=False):
        self.name, self.fail, self.paused = name, fail, threading.Event()
        self.spoken, self.done = [], []

    def speak(self, text, tag, on_done, on_audio, on_caption=None):
        self.spoken.append(text)
        self.on_caption = on_caption
        if self.fail:
            return on_done(NoAudioError("offline"))
        on_audio()
        self.done.append(on_done)

    def stop(self):
        self.paused.clear()

    def pause(self):
        self.paused.set()

    def resume(self):
        self.paused.clear()

    close = stop


class Popup:
    text, playing, paused, menu_open, visible = "", False, False, False, False

    def __init__(self, speed, **callbacks):
        self.callbacks, self.caption = callbacks, ""

    def show(self, text, x, y):
        self.text, self.visible = text, True

    def hide(self):
        self.visible = False

    def contains(self, x, y):
        return False

    def lang_tag(self):
        return None

    def schedule_hide(self):
        pass

    def set_loading(self, loading):
        pass

    def set_playing(self, playing, paused=False):
        self.playing, self.paused = playing, playing and paused

    def set_caption(self, text):
        self.caption = text

    def set_caption_paused(self, paused):
        pass

    def configure_captions(self, *appearance):
        pass

    def set_speed(self, speed):
        pass


class FakeHost:
    def __init__(self, engines):
        self._engines, self.timers, self.notes, self.quits = engines, [], [], 0
        self.app = None

    def engines(self):
        return self._engines

    def make_popup(self, speed, **callbacks):
        return Popup(speed, **callbacks)

    def open_settings(self):
        return None

    def after(self, ms, fn):
        self.timers.append((ms, fn))

    def notify(self, message):
        self.notes.append(message)

    def start_trigger(self, on_selection, on_press):
        self.triggered = (on_selection, on_press)

    def stop_trigger(self):
        pass

    def read_selection(self, clipboard_fallback):
        return "Selected."

    def quit(self):
        self.quits += 1


class CoreTest(unittest.TestCase):
    def make(self, *engines):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "settings.json"
        path.write_text(json.dumps(settings.DEFAULTS), encoding="utf-8")
        for p in (patch.object(settings, "PATH", str(path)),
                  patch.object(settings, "load", return_value=dict(settings.DEFAULTS)),
                  patch.object(settings, "save")):
            p.start()
            self.addCleanup(p.stop)
        self.host = FakeHost(list(engines))
        return core.App(self.host)

    def test_two_sentences_play_in_order_and_pause_holds_the_boundary(self):
        engine = Engine("macOS")
        app = self.make(engine)
        app.play("First one. Second one.", None)
        app.pump()
        self.assertEqual(engine.spoken, ["First one."])
        self.assertEqual(app.popup.caption, "First one.")
        app.popup.paused = True
        app.pause()
        engine.done[0](None)
        app.pump()
        self.assertEqual(engine.spoken, ["First one."])  # waits at the boundary while paused
        app.popup.paused = False
        app.resume()
        self.assertEqual(engine.spoken, ["First one.", "Second one."])
        engine.done[1](None)
        app.pump()
        self.assertIsNone(app._read_options)
        self.assertEqual(self.host.notes, [])

    def test_stop_ignores_late_callbacks(self):
        engine = Engine("macOS")
        app = self.make(engine)
        app.play("First one. Second one.", None)
        app.stop()
        engine.done[0](None)
        app.pump()
        self.assertEqual(engine.spoken, ["First one."])

    def test_no_audio_falls_back_to_the_next_engine(self):
        codex, voice = Engine("Codex", fail=True), Engine("macOS")
        app = self.make(codex, voice)
        app.play("Hello there.", None)
        self.assertEqual((codex.spoken, voice.spoken), (["Hello there."], ["Hello there."]))

    def captions(self, app, *transcripts):
        """Feeds Codex transcript updates and runs the caption delay timers they schedule."""
        for text in transcripts:
            app.chain._active.on_caption(text)
        app.pump()
        timers = [t for t in self.host.timers if t[0] == int(core.CAPTION_DELAY_S * 1000)]
        self.host.timers = [t for t in self.host.timers if t not in timers]
        for _, fn in timers:
            fn()

    def test_codex_reads_the_whole_selection_in_one_session(self):
        engine = Engine("Codex")
        app = self.make(engine)
        app.play("First one. Second one.", None)
        app.pump()
        self.assertEqual(engine.spoken, ["First one. Second one."])
        self.assertEqual(app.popup.caption, "")  # the transcript sets it, not the selection
        self.captions(app, "First one. Sec")
        self.assertEqual(app.popup.caption, "Sec")
        self.captions(app, "First one. Second one.")
        self.assertEqual(app.popup.caption, "Second one.")

    def test_codex_captions_from_an_old_read_are_ignored(self):
        engine = Engine("Codex")
        app = self.make(engine)
        app.play("First one. Second one.", None)
        app.stop()
        self.captions(app, "First one.")
        self.assertEqual(app.popup.caption, "")

    def test_codex_captions_are_held_while_paused(self):
        engine = Engine("Codex")
        app = self.make(engine)
        app.play("First one. Second one.", None)
        self.captions(app, "First one.")
        app.popup.paused = True
        app.pause()
        self.captions(app, "First one. Sec")
        self.assertEqual(app.popup.caption, "First one.")
        app.popup.paused = False
        app.resume()
        self.assertEqual(app.popup.caption, "Sec")

    def test_codex_failover_shows_the_whole_selection(self):
        codex, voice = Engine("Codex", fail=True), Engine("macOS")
        app = self.make(codex, voice)
        app.play("First one. Second one.", None)
        app.pump()
        self.assertEqual(voice.spoken, ["First one. Second one."])
        self.assertEqual(app.popup.caption, "First one. Second one.")

    def test_start_arms_the_trigger_and_the_update_timer(self):
        app = self.make(Engine("Codex"))
        app.start()
        self.assertTrue(hasattr(self.host, "triggered"))
        self.assertEqual(self.host.timers[0][0], 30_000)

    def test_quit_stops_through_the_host(self):
        app = self.make(Engine("Codex"))
        app._handle("quit")
        self.assertEqual(self.host.quits, 1)

    def test_macos_update_check_only_reports_the_version(self):
        app = self.make(Engine("Codex"))
        asset = {"version": "9.0.0", "name": "CodexSpeak.dmg"}
        with patch.object(sys, "platform", "darwin"), patch.object(sys, "frozen", True, create=True), \
                patch.object(updates, "check", return_value=asset), \
                patch.object(updates, "download") as download, patch.object(updates, "install") as install:
            app.check_update()
            for _ in range(100):
                if not app.events.empty():
                    break
                threading.Event().wait(0.01)
            app.pump()
        download.assert_not_called()
        install.assert_not_called()
        self.assertEqual(app.available_version(), "9.0.0")
        self.assertIsNone(app._pending_update)
        self.assertEqual(app.update_state(), ("v9.0.0 is available.", False))


if __name__ == "__main__":
    unittest.main()
