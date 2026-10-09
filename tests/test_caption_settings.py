import json
import gc
import tempfile
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

from PIL import Image
from codex_speak import settings
from codex_speak import settings_ui


class CaptionSettings(unittest.TestCase):
    def test_defaults_and_caption_preferences_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(settings.load(path), settings.DEFAULTS)

            saved = {**settings.DEFAULTS, "caption_font_size": 16, "caption_background": True,
                     "caption_background_opacity": 0.35}
            settings.save(saved, str(path))

            self.assertEqual(settings.load(path), saved)

    def test_caption_preferences_validate_types_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"

            for font_size, expected in ((7, 8), (28, 24), (True, 10), (12.0, 10), ("12", 10),
                                        (10 ** 400, 24)):
                path.write_text(json.dumps({"caption_font_size": font_size}), encoding="utf-8")
                self.assertEqual(settings.load(path)["caption_font_size"], expected, repr(font_size))

            for opacity, expected in ((-0.2, 0.0), (1.5, 1.0), (True, 0.6), ("0.4", 0.6),
                                      (float("nan"), 0.6), (float("inf"), 0.6), (10 ** 400, 0.6)):
                path.write_text(json.dumps({"caption_background_opacity": opacity}), encoding="utf-8")
                self.assertEqual(settings.load(path)["caption_background_opacity"], expected, repr(opacity))

            for background in ("false", 1, None):
                path.write_text(json.dumps({"caption_background": background}), encoding="utf-8")
                self.assertFalse(settings.load(path)["caption_background"], repr(background))


class CaptionSettingsUi(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.window = None

    def tearDown(self):
        if self.window and self.window.alive:
            self.window.close()
        root = self.root
        root.destroy()
        self.window = self.root = None
        root = None
        gc.collect()  # Tk cycles must release their interpreter on its owning thread.

    def make_window(self, cfg, on_change, on_test=lambda _text: None):
        with patch.object(settings_ui.settings, "startup_enabled", return_value=False), \
                patch.object(settings_ui.SettingsWindow, "focus", lambda self: self._refresh_stt()), \
                patch.object(settings_ui, "stt_connection", return_value=("", "")):
            self.window = settings_ui.SettingsWindow(self.root, cfg, Image.new("RGBA", (32, 32)),
                                                    on_change, on_test)
            return self.window

    def test_background_controls_opacity_and_keeps_its_choice(self):
        cfg = dict(settings.DEFAULTS)
        self.make_window(cfg, lambda *args: None)
        try:
            self.assertTrue(self.window.caption_opacity_scale.instate(["disabled"]))
            chosen = self.window.caption_opacity.get()
            self.window.caption_background_check.invoke()
            self.assertFalse(self.window.caption_opacity_scale.instate(["disabled"]))
            self.window.caption_background_check.invoke()
            self.assertTrue(self.window.caption_opacity_scale.instate(["disabled"]))
            self.assertEqual(self.window.caption_opacity.get(), chosen)
        finally:
            self.window.close()

    def test_settings_scroll_to_fit_small_work_area(self):
        area = SimpleNamespace(left=0, top=0, right=1920, bottom=1032)
        with patch.object(settings_ui, "work_area", return_value=area):
            self.make_window(dict(settings.DEFAULTS), lambda *args: None)
        self.window.win.deiconify()
        self.root.update()

        self.assertLessEqual(self.window.win.winfo_height(), area.bottom - area.top - 48)
        self.assertEqual(self.window._scrollbar.winfo_manager(), "pack")
        self.assertLess(self.window._scroll_canvas.winfo_height(), self.window.content.winfo_reqheight())
        self.assertTrue(self.window.close_button.winfo_viewable())

        self.window._scroll_canvas.yview_moveto(1)
        self.root.update_idletasks()
        content_bottom = self.window.stt_status.winfo_rooty() + self.window.stt_status.winfo_height()
        viewport_bottom = self.window._scroll_canvas.winfo_rooty() + self.window._scroll_canvas.winfo_height()
        self.assertLessEqual(content_bottom, viewport_bottom)

    def test_fractional_opacity_change_rounds_applies_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            cfg = dict(settings.DEFAULTS)

            def on_change(key, value, save=True):
                cfg[key] = value
                if save:
                    settings.save(cfg, str(path))

            self.make_window(dict(cfg), on_change)
            self.window.caption_background_check.invoke()
            self.window.caption_opacity.set(73.4)
            self.assertEqual(self.window.caption_opacity_label["text"], "73%")
            self.assertEqual(cfg["caption_background_opacity"], 0.73)
            self.window.close()
            self.assertEqual(settings.load(path)["caption_background_opacity"], 0.73)

    def test_close_and_test_voice_flush_pending_speed_and_caption_settings(self):
        for flush_with_test_voice in (False, True):
            with self.subTest(flush_with_test_voice=flush_with_test_voice), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "settings.json"
                cfg = dict(settings.DEFAULTS)
                test_voices = []

                def on_change(key, value, save=True):
                    cfg[key] = value
                    if save:
                        settings.save(cfg, str(path))

                self.make_window(dict(cfg), on_change, test_voices.append)
                try:
                    self.window.speed.set(1.35)
                    self.window._speed_changed("1.35")
                    self.window.caption_font_size.delete(0, "end")
                    self.window.caption_font_size.insert(0, "18")
                    self.window.caption_background_check.invoke()
                    self.window.caption_opacity.set(73)

                    if flush_with_test_voice:
                        self.window._test()
                    else:
                        self.window.close()

                    saved = settings.load(path)
                    self.assertEqual(saved["speed"], 1.35)
                    self.assertEqual(saved["caption_font_size"], 18)
                    self.assertTrue(saved["caption_background"])
                    self.assertEqual(saved["caption_background_opacity"], 0.73)
                    self.assertEqual(bool(test_voices), flush_with_test_voice)
                finally:
                    if self.window.alive:
                        self.window.close()


if __name__ == "__main__":
    unittest.main()
