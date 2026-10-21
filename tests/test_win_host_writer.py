"""Windows host contracts with mocked hooks, editors, clipboard and providers."""
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

from copy import deepcopy
import queue
from unittest.mock import Mock, call, patch

from harness_discussion import settings
from harness_discussion.win import host


class HostWriter(unittest.TestCase):
    def setUp(self):
        with patch.object(host.tk, "Tk"), patch.object(host.pystray, "Icon"), \
                patch.object(host, "icon_image"):
            self.host = host.TkHost()
        self.app = self.host.app = Mock(cfg=deepcopy(settings.DEFAULTS), events=queue.Queue())
        self.app.chain.engines = []
        self.app.statuses = {}
        self.app.rewriting = False
        self.app.writer_models = {"Codex": [{"id": "example", "efforts": []}]}
        self.app.writer_statuses = {"Codex": "ready"}

    def test_recording_pauses_and_restores_all_shortcuts_without_saving(self):
        saved = deepcopy(self.app.cfg)
        with patch.object(host, "SettingsWindow") as window:
            self.host.open_settings()
            record = window.call_args.kwargs["on_record"]
            record(True)
            record(False)
        self.assertEqual(self.app.apply.call_args_list,
                         [call(key, "") for key in ("hotkey", "rewrite_hotkey", "dictate_hotkey")]
                         + [call(key, saved[key]) for key in ("hotkey", "rewrite_hotkey", "dictate_hotkey")])
        self.assertEqual(self.app.cfg, saved)

    def test_settings_reads_current_cached_writer_data_and_routes_fixes(self):
        with patch.object(host, "SettingsWindow") as window:
            self.host.open_settings()
            callbacks = window.call_args.kwargs
        self.assertEqual(callbacks["writer_catalogs"](), self.app.writer_models)
        self.app.writer_statuses = {"Codex": "signed_out"}
        self.assertEqual(callbacks["writer_statuses"](), {"Codex": "signed_out"})
        callbacks["on_writer_fix"]("Codex")
        self.app.fix_writer.assert_called_once_with("Codex")
        self.app.refresh_writer.assert_not_called()

    def test_recording_cancels_writer_before_disabling_its_hold_listener(self):
        actions = []
        self.app.apply.side_effect = lambda key, value: actions.append(key)
        with patch.object(host, "Escape"):
            self.host.esc_watcher(lambda: actions.append("cancel"))
        with patch.object(host, "SettingsWindow") as window:
            self.host.open_settings()
            window.call_args.kwargs["on_record"](True)
        self.assertEqual(actions, ["cancel", "hotkey", "rewrite_hotkey", "dictate_hotkey"])

    def test_named_hold_shortcut_dispatches_and_replacement_stops_its_old_listener(self):
        actions = []
        with patch.object(host, "HotKey") as hook:
            self.host.set_shortcut("dictate", "<ctrl>+<shift>+d", lambda: actions.append("down"),
                                   lambda: actions.append("up"))
            hook.call_args.args[1]()
            hook.call_args.args[2]()
            self.assertEqual(actions, ["down", "up"])
            self.host.set_shortcut("dictate", "", None)
            hook.return_value.stop.assert_called_once_with()
            self.assertEqual(hook.call_count, 1)

    def test_popup_escape_is_enqueued_before_the_main_thread_callback_runs(self):
        escaped = []
        with patch.object(host, "Popup") as popup:
            self.host.make_popup(1.0, on_escape=lambda: escaped.append(True))
            popup.call_args.kwargs["on_escape"]()
        self.assertEqual(escaped, [])
        kind, callback = self.app.events.get_nowait()
        self.assertEqual(kind, "call")
        callback()
        self.assertEqual(escaped, [True])
    def test_copy_preserves_unicode_and_whitespace_and_reports_failure_without_retry(self):
        with patch.object(host, "clipboard", create=True) as clipboard:
            self.assertTrue(self.host.copy_text(" A😀\r\nB "))
            clipboard.restore.assert_called_once_with([(13, " A😀\r\nB \0".encode("utf-16-le"))])
            clipboard.restore.reset_mock()
            clipboard.restore.side_effect = OSError("clipboard unavailable")
            self.assertFalse(self.host.copy_text("private result"))
            clipboard.restore.assert_called_once()
        notification = self.host.icon.notify.call_args.args[0]
        self.assertNotIn("private result", notification)

    def test_copy_refuses_embedded_nul_before_touching_clipboard(self):
        with patch.object(host, "clipboard", create=True) as clipboard:
            self.assertFalse(self.host.copy_text("first\0second"))
            clipboard.restore.assert_not_called()

    def test_mode_menu_callbacks_keep_their_own_names_and_current_selection(self):
        chosen = []
        with patch.object(host.tk, "Menu") as menu, patch.object(host.tk, "StringVar") as choice, \
                patch.object(self.host, "pointer", return_value=(120, 240)):
            self.host.pick_mode(["Fix errors", "Email"], "Email", chosen.append)
            self.assertEqual(choice.call_args.kwargs["value"], "Email")
            entries = menu.return_value.add_radiobutton.call_args_list
            self.assertEqual([entry.kwargs["label"] for entry in entries], ["Fix errors", "Email"])
            for entry in entries:
                entry.kwargs["command"]()
            menu.return_value.post.assert_called_once_with(120, 240)
        self.assertEqual(chosen, ["Fix errors", "Email"])

    def test_quit_stops_all_owned_hooks_before_destroying_tk(self):
        events = []
        with patch.object(host, "HotKey") as hook, patch.object(host, "Escape") as escape:
            self.host.set_hotkey("<ctrl>+<alt>+r", lambda: None)
            self.host.set_shortcut("rewrite", "<ctrl>+<shift>+e", lambda: None)
            self.host.set_shortcut("dictate", "<ctrl>+<shift>+d", lambda: None, lambda: None)
            self.host.esc_watcher(lambda: None)
            hook.return_value.stop.side_effect = lambda: events.append("hook")
            escape.return_value.stop.side_effect = lambda: events.append("escape")
            self.host.root.destroy.side_effect = lambda: events.append("destroy")
            with patch.object(host.uia_thread, "close"):
                self.host.quit()
        self.assertEqual(events, ["hook", "hook", "hook", "escape", "destroy"])

    def test_toast_escape_observes_and_rewrite_escape_suppresses_without_tk_access(self):
        escaped = []
        with patch.object(host, "Escape", create=True) as listener:
            watcher = self.host.esc_watcher(lambda: escaped.append(True))
            self.assertIs(watcher, listener.return_value)
            self.assertFalse(listener.call_args.kwargs["autostart"])
            suppress = listener.call_args.kwargs["suppress"]
            self.assertFalse(suppress())
            self.app.rewriting = True
            self.assertTrue(suppress())
            listener.call_args.args[0]()
        self.assertEqual(escaped, [])
        kind, callback = self.app.events.get_nowait()
        self.assertEqual(kind, "call")
        callback()
        self.assertEqual(escaped, [True])


class AppWriterTk(unittest.TestCase):
    def setUp(self):
        from contextlib import ExitStack
        from harness_discussion import app_summarize, core
        from harness_discussion.edit_logic import Context
        from tests.test_popup_settings import Speech

        self.boundaries = ExitStack()
        self.addCleanup(self.boundaries.close)
        cfg = deepcopy(settings.DEFAULTS)
        cfg.update(writer=True, stt_server=False)
        self.editor = Mock(NEWLINE="\r\n")
        self.editor.capture.return_value = Context("an original", 1, 2, True, False)
        self.editor.same_context.return_value = True
        self.editor.replace.return_value = True
        voice = Speech("Codex")
        for target, name, kwargs in (
                (settings, "PATH", {"new": __file__}),
                (settings, "load", {"return_value": cfg}),
                (host.TkHost, "edit", {"new": self.editor, "create": True}),
                (host.TkHost, "engines", {"return_value": [voice]}),
                (host.pystray, "Icon", {}),
                (host, "HotKey", {}), (host, "Escape", {}),
                (app_summarize.summarize, "Server", {}),
                (app_summarize.summarize, "status", {"return_value": "missing"})):
            self.boundaries.enter_context(patch.object(target, name, **kwargs))
        self.host = host.TkHost()
        self.app = core.App(self.host)
        self.app.writer_sources = [Mock(name="test-source")]
        self.app.writer_sources[0].name = "Codex"
        self.app.writer_sources[0].status.return_value = "ready"
        self.app.writer_sources[0].rewrite.return_value = "A rewrite."
        self.copied = self.boundaries.enter_context(patch.object(self.host, "copy_text"))
        self.addCleanup(self.cleanup_tk)

    def cleanup_tk(self):
        import gc
        self.app._close_writer()
        self.app.chain.close()
        self.host.root.destroy()
        self.host.app = None
        self.app = self.host = None
        gc.collect()

    def rewrite_from_bar(self):
        self.app.popup.show("an original", 140, 140, editable=True)
        self.host.root.update()
        self.app.popup.rewrite_btn.command()
        self.assertTrue(self.app.rewriting)
        self.assertTrue(self.app.toast.visible)
        self.app._handle(*self.app.events.get(timeout=5))
        self.host.root.update()

    def test_real_app_bar_and_toast_open_review_with_the_current_result(self):
        from tests.test_win_writer_ui import click
        self.rewrite_from_bar()
        self.editor.replace.assert_called_once_with("A rewrite.", self.editor.capture.return_value)
        self.assertFalse(self.app.rewriting)
        self.assertFalse(self.app.popup.visible)
        click(self.host.root, self.app.toast.win, "Review")
        self.assertTrue(self.app.review.visible)
        self.assertEqual(self.app.review.result(), "A rewrite.")
        click(self.host.root, self.app.review.win, "Copy")
        self.copied.assert_called_once_with("A rewrite.")

    def test_changed_target_offers_copy_without_pasting(self):
        from tests.test_win_writer_ui import click
        self.editor.same_context.return_value = False
        self.rewrite_from_bar()
        self.editor.replace.assert_not_called()
        click(self.host.root, self.app.toast.win, "Copy")
        self.copied.assert_called_once_with("A rewrite.")

