import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image
from select_to_tts import settings_ui


class SttSettings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, LOCALAPPDATA=self.temp.name)
        self.env.start()
        self.path = Path(self.temp.name) / "select-to-tts/stt-connection.json"
        self.path.parent.mkdir()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def save(self, url):
        self.path.write_text(json.dumps({"base_url": url, "model": "codex-realtime"}), encoding="utf-8")

    def test_only_local_connection_is_accepted(self):
        self.save("http://127.0.0.1:18765/example/v1")
        self.assertEqual(settings_ui.stt_connection()[1], "codex-realtime")
        self.save("https://example.com/v1")
        with self.assertRaises(ValueError):
            settings_ui.stt_connection()

    def test_copy_refresh_and_missing_file(self):
        self.save("http://127.0.0.1:18765/example/v1")
        root = tk.Tk()
        root.withdraw()
        window = None
        try:
            with patch.object(settings_ui.settings, "startup_enabled", return_value=False), patch.object(settings_ui.SettingsWindow, "focus", lambda self: self._refresh_stt()):
                window = settings_ui.SettingsWindow(root, dict(settings_ui.settings.DEFAULTS), Image.new("RGBA", (32, 32)), lambda *a: None, lambda *a: None)
            window.win.withdraw()
            self.assertEqual(window.stt_values["Model"].get(), "codex-realtime")
            self.save("http://127.0.0.1:18765/changed/v1")
            # Exercise native button callbacks without changing the user's clipboard.
            with patch.object(window.win, "clipboard_clear") as clear, patch.object(window.win, "clipboard_append") as append:
                window.stt_copy_buttons[0].invoke()
                clear.assert_called_once()
                append.assert_called_with("http://127.0.0.1:18765/changed/v1")
                window.stt_copy_buttons[1].invoke()
                append.assert_called_with("codex-realtime")
            self.path.unlink()
            window._refresh_stt()
            self.assertEqual(window.stt_values["Server URL"].get(), "")
            self.assertTrue(all(str(b["state"]) == "disabled" for b in window.stt_copy_buttons))
        finally:
            if window:
                window.close()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
