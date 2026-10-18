"""Windows-only logic: clipboard formats, the mouse hook, SAPI rate, and the sign-in task."""
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

from pynput.mouse import Button

from codex_speak import settings
from unittest import mock

from codex_speak.win import clipboard, selection
from codex_speak.win.trigger import SelectionTrigger
from codex_speak.win.voice import sapi_rate


class Clipboard(unittest.TestCase):
    def test_safe_to_borrow(self):
        self.assertTrue(clipboard.safe_to_borrow(set()))
        self.assertTrue(clipboard.safe_to_borrow({13, 1, 7, 16, 49353}))  # text + HTML Format
        self.assertTrue(clipboard.safe_to_borrow({2, 8, 17}))  # bitmap backed by a DIB
        self.assertFalse(clipboard.safe_to_borrow({2}))  # bare HBITMAP
        self.assertFalse(clipboard.safe_to_borrow({14, 13}))  # enhanced metafile


class ListNumbers(unittest.TestCase):
    def read(self, uia, window="Chrome_WidgetWin_1", fallback=True,
             html="<p>Please:</p><ol><li>A</li><li>B</li></ol>"):
        with mock.patch.object(selection, "_via_uia", return_value=uia), \
                mock.patch.object(selection, "_foreground_class", return_value=window), \
                mock.patch.object(selection, "_via_clipboard", return_value=("copied", html)) as self.copy:
            return selection.read(fallback)

    def test_web_list_numbers_come_from_the_copied_html(self):
        self.assertEqual(self.read("Please:\nA\nB"), "Please:\n1. A\n2. B")

    def test_other_apps_settings_and_text_are_left_alone(self):
        for kw in ({"window": "OpusApp"}, {"fallback": False}):
            self.assertEqual(self.read("Please:\nA\nB", **kw), "Please:\nA\nB")
            self.copy.assert_not_called()
        self.assertEqual(self.read("Please:\n1. A"), "Please:\n1. A")
        self.copy.assert_not_called()
        self.assertEqual(self.read("A\nB", html="<ul><li>A</li></ul>"), "A\nB")


class Trigger(unittest.TestCase):
    def test_drag_and_double_click(self):
        hits = []
        t = SelectionTrigger(lambda x, y: hits.append((x, y)), lambda x, y: None)
        click = lambda x, y: (t._click(x, y, Button.left, True), t._click(x, y, Button.left, False))
        t._click(0, 0, Button.left, True)
        t._click(100, 0, Button.left, False)  # drag
        click(500, 500)  # single click: nothing
        click(500, 500)  # second click: double-click
        t._click(0, 0, Button.right, True)  # other buttons ignored
        self.assertEqual(hits, [(100, 0), (500, 500)])


class SignInTask(unittest.TestCase):
    def test_startup_round_trip(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        service, tasks = MagicMock(), {}
        folder = service.GetFolder.return_value
        folder.GetTask.side_effect = lambda name: tasks[name]
        folder.RegisterTaskDefinition.side_effect = lambda name, *args: tasks.update({name: SimpleNamespace(Enabled=True)})
        folder.DeleteTask.side_effect = lambda name, flags: tasks.pop(name)
        with patch.object(settings, "_scheduler", return_value=service):
            name = "codex-speak-unittest"
            try:
                settings.set_startup(True, name)
                self.assertTrue(settings.startup_enabled(name))
                tasks[name].Enabled = False
                self.assertFalse(settings.startup_enabled(name))
                settings.set_startup(False, name)
                self.assertFalse(settings.startup_enabled(name))
                settings.set_startup(False, name)  # already off: no error
            finally:
                settings.set_startup(False, name)


    def test_installed_build_replaces_the_old_task(self):
        from unittest.mock import call, patch
        replaced = [call(True), call(False, settings.LEGACY_TASK)]
        for old_enabled, expected in ((True, replaced), (False, replaced[1:])):  # a disabled one stays off
            with patch.object(settings.sys, "frozen", True, create=True), \
                    patch.object(settings, "_task_enabled", side_effect=lambda name: old_enabled if name == settings.LEGACY_TASK else None), \
                    patch.object(settings, "startup_enabled", return_value=False), \
                    patch.object(settings, "set_startup") as set_startup, \
                    patch.object(settings.winreg, "OpenKey", side_effect=OSError):
                settings.refresh_startup()
            self.assertEqual(set_startup.call_args_list, expected, old_enabled)

    def test_source_run_leaves_the_old_task_alone(self):
        from unittest.mock import patch
        with patch.object(settings.sys, "frozen", False, create=True), \
                patch.object(settings, "startup_enabled", return_value=True), \
                patch.object(settings, "_task_enabled", return_value=True) as old_task, \
                patch.object(settings, "set_startup") as set_startup, \
                patch.object(settings.winreg, "OpenKey", side_effect=OSError):
            settings.refresh_startup()
        set_startup.assert_not_called()
        old_task.assert_not_called()

    def test_installed_refresh_keeps_a_disabled_current_task_off(self):
        from unittest.mock import call, patch
        for old_enabled in (None, False, True):
            for legacy_run in (False, True):
                with self.subTest(old_enabled=old_enabled, legacy_run=legacy_run), \
                        patch.object(settings.sys, "frozen", True, create=True), \
                        patch.object(settings, "_task_enabled", side_effect=lambda name: old_enabled if name == settings.LEGACY_TASK else False), \
                        patch.object(settings, "set_startup") as set_startup, \
                        patch.object(settings, "_drop_run_value") as drop_run, \
                        patch.object(settings.winreg, "QueryValueEx", return_value=("SelectToTTS.exe", 1)), \
                        patch.object(settings.winreg, "OpenKey", side_effect=None if legacy_run else OSError):
                    settings.refresh_startup()
                self.assertEqual(set_startup.call_args_list, [] if old_enabled is None else [call(False, settings.LEGACY_TASK)])
                self.assertEqual(drop_run.call_count, int(legacy_run))

    def test_disabled_legacy_task_overrides_an_older_run_value(self):
        from unittest.mock import patch
        with patch.object(settings.sys, "frozen", True, create=True), \
                patch.object(settings, "_task_enabled", side_effect=lambda name: False if name == settings.LEGACY_TASK else None), \
                patch.object(settings, "set_startup") as set_startup, \
                patch.object(settings, "_drop_run_value") as drop_run, \
                patch.object(settings.winreg, "QueryValueEx", return_value=("SelectToTTS.exe", 1)), \
                patch.object(settings.winreg, "OpenKey"):
            settings.refresh_startup()
        set_startup.assert_called_once_with(False, settings.LEGACY_TASK)
        drop_run.assert_called_once()

    def test_installed_disable_removes_both_disabled_tasks(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch
        service = MagicMock()
        tasks = {name: SimpleNamespace(Enabled=False) for name in (settings.TASK, settings.LEGACY_TASK)}
        folder = service.GetFolder.return_value
        folder.GetTask.side_effect = lambda name: tasks[name]
        folder.DeleteTask.side_effect = lambda name, flags: tasks.pop(name)
        with patch.object(settings.sys, "frozen", True, create=True), \
                patch.object(settings, "_scheduler", return_value=service), \
                patch.object(settings, "_drop_run_value"):
            settings.set_startup(False)
        self.assertEqual(tasks, {})

    def test_source_run_leaves_the_legacy_run_value_alone(self):
        from unittest.mock import patch
        with patch.object(settings.sys, "frozen", False, create=True), \
                patch.object(settings, "set_startup") as set_startup, \
                patch.object(settings.winreg, "OpenKey"), \
                patch.object(settings.winreg, "QueryValueEx", return_value=("SelectToTTS.exe", 1)) as query:
            settings.refresh_startup()
        query.assert_called_once()
        set_startup.assert_not_called()



class SapiRate(unittest.TestCase):
    def test_sapi_rate(self):
        self.assertEqual([sapi_rate(s) for s in (0.5, 1.0, 1.5, 2.0, 3.0)], [-6, 0, 4, 6, 10])



if __name__ == "__main__":
    unittest.main()
