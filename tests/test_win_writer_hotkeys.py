"""Windows HotKey: the read shortcut must not regress, and hold-to-dictate callbacks (plan T7)."""
import sys
import unittest

if sys.platform != "win32":
    raise unittest.SkipTest("Windows only")

from unittest import mock

from pynput.keyboard import Key, KeyCode

from harness_discussion.win.trigger import HotKey


def make(spec, hold):
    """A HotKey over an inert mocked keyboard.Listener, with its captured callbacks."""
    downs, ups = [], []
    with mock.patch("harness_discussion.win.trigger.keyboard.Listener") as listener:
        hotkey = HotKey(spec, lambda: downs.append(1), on_release=(lambda: ups.append(1)) if hold else None)
        press, release = listener.call_args.kwargs["on_press"], listener.call_args.kwargs["on_release"]
        inert = listener.return_value
    return hotkey, downs, ups, press, release, inert


class ReadShortcut(unittest.TestCase):
    """The default tap behavior: fire once every key of the shortcut is up, so a borrowed Ctrl+C survives."""

    def test_fires_once_every_key_is_up_and_nothing_while_they_are_down(self):
        hotkey, downs, ups, press, release, _ = make("<ctrl>+<alt>+r", hold=False)
        press(Key.ctrl_l)
        press(Key.alt_l)
        press(KeyCode(vk=0x52, char="ר"))  # R on a Hebrew layout: the virtual key is what counts
        self.assertEqual(downs, [])  # not while the keys are held
        for key in (KeyCode(vk=0x52), Key.alt_l, Key.ctrl_l):
            release(key)
        self.assertEqual(downs, [1])

    def test_an_extra_modifier_is_not_the_chord(self):
        hotkey, downs, ups, press, release, _ = make("<ctrl>+<alt>+r", hold=False)
        for key in (Key.ctrl_l, Key.shift, Key.alt_l, KeyCode(vk=0x52)):
            press(key)
        for key in (KeyCode(vk=0x52), Key.alt_l, Key.shift, Key.ctrl_l):
            release(key)
        self.assertEqual(downs, [])  # Ctrl+Alt+Shift+R isn't Ctrl+Alt+R

    def test_stop_stops_the_listener(self):
        hotkey, downs, ups, press, release, inert = make("<ctrl>+<alt>+r", hold=False)
        hotkey.stop()
        inert.stop.assert_called_once()


class HoldToDictate(unittest.TestCase):
    """With on_release, the down fires on the exact chord and the up fires once the chord is all released."""

    def test_waits_for_both_physical_control_keys_to_release(self):
        hotkey, downs, ups, press, release, _ = make("<ctrl>+<alt>+r", hold=True)
        for key in (Key.ctrl_l, Key.ctrl_r, Key.alt_l, KeyCode(vk=0x52)):
            press(key)
        self.assertEqual(downs, [1])
        for key in (Key.ctrl_l, Key.alt_l, KeyCode(vk=0x52)):
            release(key)
        self.assertEqual(ups, [])
        release(Key.ctrl_r)
        self.assertEqual(ups, [1])

    def test_down_fires_on_the_exact_chord_and_up_fires_after_the_full_release(self):
        hotkey, downs, ups, press, release, _ = make("<ctrl>+<alt>+r", hold=True)
        press(Key.ctrl_l)
        press(Key.alt_l)
        self.assertEqual(downs, [])  # a partial chord hasn't matched yet
        press(KeyCode(vk=0x52, char="ר"))
        self.assertEqual(downs, [1])  # the down fires while the chord is still held
        self.assertEqual(ups, [])  # not before everything is released
        for key in (KeyCode(vk=0x52), Key.alt_l, Key.ctrl_l):
            release(key)
        self.assertEqual(downs, [1])
        self.assertEqual(ups, [1])

    def test_auto_repeat_and_a_partial_release_never_fire_a_second_down(self):
        hotkey, downs, ups, press, release, _ = make("<ctrl>+<alt>+r", hold=True)
        for key in (Key.ctrl_l, Key.alt_l, KeyCode(vk=0x52, char="ר")):
            press(key)
        self.assertEqual(downs, [1])
        for _ in range(3):
            press(KeyCode(vk=0x52, char="ר"))  # Windows auto-repeat re-sends the same key-down
        release(KeyCode(vk=0x52))  # partially released...
        press(KeyCode(vk=0x52, char="ר"))  # ...and pressed again while Ctrl+Alt are still held
        self.assertEqual(downs, [1])
        self.assertEqual(ups, [])  # not released yet, so the up hasn't fired
        for key in (KeyCode(vk=0x52), Key.alt_l, Key.ctrl_l):
            release(key)
        self.assertEqual(downs, [1])
        self.assertEqual(ups, [1])  # exactly one up, once everything is released

    def test_an_extra_modifier_is_not_the_chord_and_fires_nothing(self):
        hotkey, downs, ups, press, release, _ = make("<ctrl>+<alt>+r", hold=True)
        for key in (Key.ctrl_l, Key.shift, Key.alt_l, KeyCode(vk=0x52, char="r")):
            press(key)
        self.assertEqual(downs, [])  # Ctrl+Alt+Shift+R isn't Ctrl+Alt+R
        for key in (Key.shift, KeyCode(vk=0x52), Key.alt_l, Key.ctrl_l):
            release(key)
        self.assertEqual((downs, ups), ([], []))  # no down ever fired, so no up either

    def test_rearms_after_a_full_cycle(self):
        hotkey, downs, ups, press, release, _ = make("<ctrl>+<alt>+r", hold=True)
        for cycle in range(2):
            for key in (Key.ctrl_l, Key.alt_l, KeyCode(vk=0x52, char="r")):
                press(key)
            for key in (KeyCode(vk=0x52), Key.alt_l, Key.ctrl_l):
                release(key)
        self.assertEqual(downs, [1, 1])  # each hold fires its own down
        self.assertEqual(ups, [1, 1])  # and its own up

    def test_stop_stops_the_listener(self):
        hotkey, downs, ups, press, release, inert = make("<ctrl>+<alt>+r", hold=True)
        hotkey.stop()
        inert.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
