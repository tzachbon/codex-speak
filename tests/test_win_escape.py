"""Temporary Esc hook with an inert listener, never a real keyboard hook."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

from harness_discussion.win import trigger


class EscapeHook(unittest.TestCase):
    def test_watcher_can_be_created_inactive_and_reused(self):
        action = Mock()
        listeners = [Mock(), Mock()]
        with patch.object(trigger.keyboard, "Listener", side_effect=listeners) as make_listener:
            watcher = trigger.Escape(action, autostart=False)
            self.assertFalse(watcher.active)
            make_listener.assert_not_called()

            watcher.start()
            first = listeners[0]
            self.assertTrue(watcher.active)
            watcher.start()
            make_listener.assert_called_once()
            first.start.assert_called_once()

            watcher.stop()
            watcher.stop()
            self.assertFalse(watcher.active)
            first.stop.assert_called_once()

            watcher.start()
            second = listeners[1]
            self.assertTrue(watcher.active)
            self.assertIsNot(first, second)
            second.start.assert_called_once()
            watcher.stop()
            self.assertFalse(watcher.active)

    def test_callbacks_from_an_old_listener_are_ignored_after_restart(self):
        action = Mock()
        listeners = [Mock(), Mock()]
        with patch.object(trigger.keyboard, "Listener", side_effect=listeners) as make_listener:
            watcher = trigger.Escape(action, autostart=False)
            watcher.start()
            old_filter = make_listener.call_args.kwargs["win32_event_filter"]
            watcher.stop()
            old_filter(0x100, SimpleNamespace(vkCode=27))
            action.assert_not_called()

            watcher.start()
            new_filter = make_listener.call_args.kwargs["win32_event_filter"]

            old_filter(0x100, SimpleNamespace(vkCode=27))
            action.assert_not_called()
            listeners[0].suppress_event.assert_not_called()
            listeners[1].suppress_event.assert_not_called()

            new_filter(0x100, SimpleNamespace(vkCode=27))
            action.assert_called_once_with()
            listeners[1].suppress_event.assert_called_once_with()
            watcher.stop()

    def test_failed_start_stays_inactive_and_can_be_retried(self):
        action = Mock()
        failed, recovered = Mock(), Mock()
        failed.start.side_effect = RuntimeError("listener did not start")
        with patch.object(trigger.keyboard, "Listener", side_effect=[failed, recovered]):
            watcher = trigger.Escape(action, autostart=False)
            with self.assertRaisesRegex(RuntimeError, "listener did not start"):
                watcher.start()
            self.assertFalse(watcher.active)
            failed.stop.assert_called_once_with()

            watcher.start()
            self.assertTrue(watcher.active)
            recovered.start.assert_called_once_with()
            watcher.stop()
            self.assertFalse(watcher.active)

    def test_stop_and_restart_inside_suppress_cannot_redirect_old_filter(self):
        action = Mock()
        listeners = [Mock(), Mock()]
        watcher_ref = []

        def replace_watcher():
            watcher_ref[0].stop()
            watcher_ref[0].start()
            return True

        with patch.object(trigger.keyboard, "Listener", side_effect=listeners) as make_listener:
            watcher = trigger.Escape(action, suppress=replace_watcher, autostart=False)
            watcher_ref.append(watcher)
            watcher.start()
            old_filter = make_listener.call_args.kwargs["win32_event_filter"]

            old_filter(0x100, SimpleNamespace(vkCode=27))

            action.assert_called_once_with()
            self.assertTrue(watcher.active)
            listeners[0].stop.assert_called_once_with()
            listeners[0].suppress_event.assert_not_called()
            listeners[1].suppress_event.assert_not_called()
            watcher.stop()

    def test_only_escape_is_suppressed_and_repeats_enqueue_once_until_release(self):
        action = Mock()
        with patch.object(trigger.keyboard, "Listener") as listener:
            watcher = trigger.Escape(action)
            self.assertTrue(watcher.active)
            listener.return_value.start.assert_called_once()
            event = listener.call_args.kwargs["win32_event_filter"]
            event(0x100, SimpleNamespace(vkCode=65))
            listener.return_value.suppress_event.assert_not_called()
            event(0x100, SimpleNamespace(vkCode=27))
            event(0x100, SimpleNamespace(vkCode=27))
            action.assert_called_once_with()
            event(0x101, SimpleNamespace(vkCode=27))
            event(0x100, SimpleNamespace(vkCode=27))
            self.assertEqual(action.call_count, 2)
            self.assertEqual(listener.return_value.suppress_event.call_count, 4)
            watcher.stop()
            watcher.stop()
            listener.return_value.stop.assert_called_once()

    def test_toast_only_watcher_can_observe_without_suppressing(self):
        action = Mock()
        with patch.object(trigger.keyboard, "Listener") as listener:
            watcher = trigger.Escape(action, suppress=lambda: False)
            event = listener.call_args.kwargs["win32_event_filter"]
            self.assertFalse(event(0x100, SimpleNamespace(vkCode=27)))
            action.assert_called_once_with()
            listener.return_value.suppress_event.assert_not_called()
            watcher.stop()
            listener.return_value.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
