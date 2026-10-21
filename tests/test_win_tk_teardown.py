"""Tk fixtures must release their objects before a later worker collects garbage."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")


class TkTeardown(unittest.TestCase):
    def test_popup_fixtures_leave_no_tk_objects_for_background_collection(self):
        script = r'''
import gc, sys, threading, unittest
from unittest.mock import patch
from harness_discussion.win import trigger
errors = []
sys.unraisablehook = lambda err: errors.append((threading.current_thread().name, str(err.exc_value)))
with patch.object(trigger.keyboard, "Listener"), patch.object(trigger.mouse, "Listener"):
    suite = unittest.defaultTestLoader.loadTestsFromNames(["tests.test_win_writer_popup.WriterBar"])
    result = unittest.TextTestRunner().run(suite)
del suite
collector = threading.Thread(target=gc.collect, name="teardown-check")
collector.start()
collector.join()
gc.collect()
if errors:
    print("Unraisable Tk errors:", errors, file=sys.stderr)
sys.exit(not result.wasSuccessful() or bool(errors))
'''
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=root,
                                env={**os.environ, "PYTHONPATH": str(root / "src")},
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("invalid command name", result.stderr)
