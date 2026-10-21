"""Windows Writer bar layouts and the actions retained in overflow."""
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

import tkinter as tk
from unittest.mock import patch

from harness_discussion.win.popup import Popup
from harness_discussion.writer import BUILTIN_MODES


class WriterBar(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.calls = []
        callback = lambda *args: None
        self.bar = Popup(self.root, 1, on_play=callback, on_stop=callback, on_pause=callback,
                         on_resume=callback, on_lang=callback, on_speed=callback,
                         on_settings=lambda: self.calls.append("settings"), on_source=callback,
                         sources=lambda: [], on_skip=callback)
        self.addCleanup(self.root.destroy)
        self.addCleanup(self.bar.hide)

    def test_reading_layout_keeps_only_play_summary_and_overflow(self):
        self.bar.show("Selected text", 140, 140)
        self.root.update()
        self.assertEqual(self.bar.win.pack_slaves(),
                         [self.bar.btn, self.bar.ai_btn, self.bar.more_btn])

    def test_writing_and_playing_layouts_restore_the_selected_mode(self):
        self.bar.configure_writer(self.calls.append, lambda: BUILTIN_MODES, lambda: "Message")
        self.bar.set_mode(True)
        self.bar.show("Selected text", 140, 140)
        self.root.update()
        left = self.bar.win.winfo_x()
        self.assertEqual(self.bar.win.pack_slaves(),
                         [self.bar.rewrite_btn, self.bar.mode_btn, self.bar.btn, self.bar.more_btn])
        self.bar.rewrite_btn.command()
        self.assertEqual(self.calls, ["Message"])
        self.bar.set_playing(True)
        self.root.update()
        self.assertEqual(self.bar.win.pack_slaves(),
                         [self.bar.btn, self.bar.back_btn, self.bar.next_btn, self.bar.stop_btn, self.bar.more_btn])
        self.assertEqual(self.bar.win.winfo_x(), left)
        self.bar.set_playing(False)
        self.assertIn(self.bar.rewrite_btn, self.bar.win.pack_slaves())
        self.bar.set_writer(False)
        self.assertEqual(self.bar.win.pack_slaves(), [self.bar.btn, self.bar.ai_btn, self.bar.more_btn])

    def test_overflow_keeps_voice_language_speed_summary_rewrite_and_settings(self):
        self.bar.configure_writer(self.calls.append, lambda: BUILTIN_MODES, lambda: "Fix errors")
        self.bar.sources = lambda: [("Codex", None)]
        self.bar.on_source = lambda name: self.calls.append(("source", name))
        self.bar.on_lang = lambda tag: self.calls.append(("language", tag))
        self.bar.on_speed = lambda speed: self.calls.append(("speed", speed))
        self.bar.on_summarize = lambda text, tag: self.calls.append(("summary", text))
        self.bar.show("Selected text", 140, 140)
        with patch.object(self.bar.overflow, "post"):
            self.bar.more_btn.command()
        menu = self.bar.overflow
        self.addCleanup(menu.unpost)
        labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
                  if menu.type(i) != "separator"]
        self.assertEqual(labels, ["Voice", "Language", "Speed", "Summarize", "Rewrite", "Settings…"])
        self.bar.sources_menu.invoke(0)
        self.bar.menu.invoke(1)
        self.bar.speed_menu.invoke(0)
        menu.invoke("Summarize")
        self.bar.mode_menu.invoke("Email")
        menu.invoke("Settings…")
        self.assertEqual(self.calls, [("source", "Codex"), ("language", "he-IL"), ("speed", 0.5),
                                     ("summary", "Selected text"), "Email", "settings"])


if __name__ == "__main__":
    unittest.main()
