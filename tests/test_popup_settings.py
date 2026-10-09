"""Native button-to-Settings checks without speech services or persistent changes."""
import gc
import json
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from select_to_tts import __main__ as main, settings, settings_ui


class Speech:
    speed = 1.0

    def __init__(self, name):
        self.name, self.paused = name, threading.Event()

    def speak(self, text, tag, done, heard):
        heard()

    def stop(self):
        self.paused.clear()

    def pause(self):
        self.paused.set()

    def resume(self):
        self.paused.clear()

    close = stop


class PopupSettings(unittest.TestCase):
    def setUp(self):
        self.boundaries = ExitStack()
        self.addCleanup(self.boundaries.close)
        directory = self.boundaries.enter_context(tempfile.TemporaryDirectory())
        path = Path(directory) / "settings.json"
        path.write_text(json.dumps(settings.DEFAULTS), encoding="utf-8")
        self.boundaries.enter_context(patch.object(settings, "PATH", str(path)))
        self.boundaries.enter_context(patch.object(settings, "load", return_value=dict(settings.DEFAULTS)))
        self.boundaries.enter_context(patch.object(settings, "startup_enabled", return_value=False))
        self.boundaries.enter_context(patch.object(settings_ui, "stt_connection", return_value=("", "")))
        for factory, name in (("CodexEngine", "Codex"), ("EdgeEngine", "Edge"), ("SapiEngine", "Windows")):
            self.boundaries.enter_context(patch.object(main, factory, return_value=Speech(name)))
        self.app = main.App()
        self.app.popup.show("A sentence to read.", 140, 140)
        self.app.root.update()

    def tearDown(self):
        if self.app.settings_win and self.app.settings_win.alive:
            self.app.settings_win.close()
        self.app.chain.close()
        self.app.popup.hide()
        self.app.icon.stop()
        self.app.trigger.stop()
        self.app.root.destroy()
        self.app = None
        gc.collect()

    def click(self, button):
        label = button.parts[1]
        label.event_generate("<ButtonPress-1>", x=2, y=2)
        label.event_generate("<ButtonRelease-1>", x=2, y=2)
        while not self.app.events.empty():
            self.app._handle(*self.app.events.get_nowait())
        self.app.root.update()

    def test_settings_pauses_speech_reuses_window_and_play_resumes_after_close(self):
        popup = self.app.popup
        self.click(popup.btn)
        self.assertTrue(popup.playing)
        self.assertFalse(popup.paused)
        read_id = self.app._read_id
        self.click(popup.settings_btn)
        window = self.app.settings_win
        self.assertTrue(window.win.winfo_viewable())
        self.assertTrue(popup.paused)
        self.assertTrue(self.app.chain.engines[0].paused.is_set())
        self.assertEqual(popup.caption.text, "A sentence to read.")
        self.assertEqual(self.app._read_id, read_id)
        self.click(popup.settings_btn)
        self.assertIs(self.app.settings_win, window)
        self.assertTrue(popup.paused)
        window.close()
        self.assertTrue(popup.paused)
        self.click(popup.btn)
        self.assertFalse(popup.paused)
        self.assertFalse(self.app.chain.engines[0].paused.is_set())
        self.assertEqual(self.app._read_id, read_id)

    def test_idle_settings_does_not_start_speech_and_closed_window_reopens(self):
        popup = self.app.popup
        self.click(popup.settings_btn)
        window = self.app.settings_win
        self.assertTrue(window.win.winfo_viewable())
        self.assertFalse(popup.playing)
        self.assertIsNone(self.app.chain._active)
        window.close()
        self.click(popup.settings_btn)
        self.assertIsNot(self.app.settings_win, window)
        self.assertTrue(self.app.settings_win.win.winfo_viewable())
        self.assertFalse(popup.playing)

    def test_opening_settings_while_already_paused_does_not_resume(self):
        popup = self.app.popup
        self.click(popup.btn)
        self.click(popup.btn)
        self.assertTrue(popup.paused)
        self.click(popup.settings_btn)
        self.assertTrue(self.app.settings_win.win.winfo_viewable())
        self.assertTrue(popup.paused)
        self.assertTrue(self.app.chain.engines[0].paused.is_set())


if __name__ == "__main__":
    unittest.main()
