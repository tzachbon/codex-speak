"""The read shortcut's stored form: parsing, building it from keys, its label, and settings validation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_discussion import hotkeys, settings


class Parse(unittest.TestCase):
    def test_valid_shortcuts(self):
        self.assertEqual(hotkeys.parse("<ctrl>+<alt>+r"), (frozenset({"ctrl", "alt"}), "r"))
        self.assertEqual(hotkeys.parse("<cmd>+<f5>"), (frozenset({"cmd"}), "f5"))

    def test_invalid_shortcuts(self):
        for spec in ("", "r", "<ctrl>", "<ctrl>+r+s", "<ctrl>+f5", "<ctrl>+<r>", "<hyper>+r", "<ctrl>+!", "<ctrl>+c", "<cmd>+c", None, 3):
            self.assertIsNone(hotkeys.parse(spec), spec)

    def test_spec_orders_modifiers_and_needs_one(self):
        self.assertEqual(hotkeys.spec({"alt", "ctrl"}, "R"), "<ctrl>+<alt>+r")
        self.assertEqual(hotkeys.spec({"shift"}, "F12"), "<shift>+<f12>")
        self.assertIsNone(hotkeys.spec(set(), "r"))
        self.assertIsNone(hotkeys.spec({"ctrl"}, "Control_L"))

    def test_label(self):
        with patch.object(hotkeys.sys, "platform", "win32"):
            self.assertEqual(hotkeys.label("<ctrl>+<alt>+r"), "Ctrl+Alt+R")
        with patch.object(hotkeys.sys, "platform", "darwin"):
            self.assertEqual(hotkeys.label("<cmd>+<alt>+r"), "⌥⌘R")
        self.assertEqual(hotkeys.label(""), "Off")


class Saved(unittest.TestCase):
    def load(self, value):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"hotkey": value}), encoding="utf-8")
            return settings.load(str(path))["hotkey"]

    def test_off_and_valid_values_are_kept_and_invalid_ones_reset(self):
        self.assertEqual(self.load(""), "")
        self.assertEqual(self.load("<shift>+<alt>+x"), "<shift>+<alt>+x")
        self.assertEqual(self.load("r"), hotkeys.DEFAULT)
        self.assertEqual(self.load(5), hotkeys.DEFAULT)
