"""Temporary Esc hook with an inert listener, never a real keyboard hook."""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

from harness_discussion.win import trigger


class EscapeHook(unittest.TestCase):
    def test_only_escape_is_suppressed_and_repeats_enqueue_once_until_release(self):
        action = Mock()
        with patch.object(trigger.keyboard, "Listener") as listener:
            watcher = trigger.Escape(action)
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
            trigger.Escape(action, suppress=lambda: False)
            event = listener.call_args.kwargs["win32_event_filter"]
            event(0x100, SimpleNamespace(vkCode=27))
            action.assert_called_once_with()
            listener.return_value.suppress_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
