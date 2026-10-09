import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import threading

from select_to_tts.__main__ import App
from select_to_tts import sentences
from select_to_tts.engines import SapiEngine


class Popup:
    text = ""
    playing = True
    paused = False
    visible = False
    menu_open = False

    def __init__(self):
        self.caption = ""
        self.lang = SimpleNamespace(get=lambda: "")

    def set_caption(self, text):
        self.caption = text

    def set_caption_paused(self, paused):
        self.paused = paused

    def set_playing(self, playing):
        self.playing, self.paused = playing, False
        if not playing:
            self.caption = ""

    def set_loading(self, loading):
        pass

    def contains(self, x, y):
        return False

    def show(self, text, x, y):
        self.text = text
        self.set_playing(False)

    def hide(self):
        self.visible = False
        self.caption = ""

    def set_speed(self, speed):
        pass

    def configure_captions(self, *appearance):
        self.appearance = appearance


class Chain:
    def __init__(self):
        self.calls, self.prepared = [], []
        self.only, self.last, self.prefetch = None, "Codex", False
        self.engines = [SimpleNamespace(speed=1.0)]

    def speak(self, text, tag, done, heard=lambda: None):
        self.calls.append((text, tag, done, heard, self.only, self.engines[0].speed))

    def prepare(self, tag, text=None):
        self.prepared.append((tag, text if self.prefetch else None))

    def stop(self):
        pass

    def pause(self):
        pass

    def resume(self):
        pass


def app():
    a = App.__new__(App)
    a.events, a._read_id = queue.Queue(), 0
    a._units, a._unit_index, a._pending_next, a._read_options = [], 0, False, None
    a.cfg = {"engine": None, "speed": 1.0, "prefetch": False}
    a.popup, a.chain, a.settings_win = Popup(), Chain(), None
    a.notifications = []
    a.icon = SimpleNamespace(notify=lambda *args: a.notifications.append(args))
    return a


def pump(a):
    while not a.events.empty():
        a._handle(*a.events.get_nowait())


class Sequence(unittest.TestCase):
    def test_caption_advances_at_output_and_pause_holds_the_boundary(self):
        a = app()
        a.play("First sentence. Second sentence!", None)
        self.assertEqual([c[0] for c in a.chain.calls], ["First sentence."])
        self.assertEqual(a.popup.caption, "")

        a.chain.calls[0][3]()
        pump(a)
        self.assertEqual(a.popup.caption, "First sentence.")
        a.pause()
        a.chain.calls[0][2](None)
        pump(a)
        self.assertEqual(len(a.chain.calls), 1)
        self.assertEqual(a.popup.caption, "First sentence.")
        a.resume()
        a.resume()
        self.assertEqual(len(a.chain.calls), 2)
        self.assertEqual(a.popup.caption, "First sentence.")
        a.chain.calls[1][3]()
        pump(a)
        self.assertEqual(a.popup.caption, "Second sentence!")
        a.chain.calls[1][2](None)
        pump(a)
        self.assertFalse(a.popup.playing)
        self.assertEqual(a.popup.caption, "")

    def test_idle_speed_change_prepares_the_same_first_unit_as_play(self):
        a = app()
        a.popup.playing = False
        a.popup.text = "Hello. שלום עולם!"
        a.cfg["prefetch"] = a.chain.prefetch = True
        a.change("speed", 0.5, save=False)
        self.assertEqual(a.chain.prepared, [("he-IL", "Hello.")])
        a.play(a.popup.text, None)
        self.assertEqual(a.chain.calls[0][:2], ("Hello.", "he-IL"))

    def test_stop_replacement_and_test_voice_ignore_late_caption_and_errors(self):
        for action in ("stop", "replacement", "test"):
            with self.subTest(action=action):
                a = app()
                a.play("Old sentence. More old text.", None)
                old = a.chain.calls[0]
                old[3]()
                pump(a)
                if action == "stop":
                    a.stop()
                elif action == "replacement":
                    a.pause()
                    a._handle("show", "New selection!", 1, 1)
                else:
                    a.test_voice("Test voice")
                old[3]()
                old[2](RuntimeError("old failure"))
                pump(a)
                self.assertEqual(a.popup.caption, "")
                self.assertEqual(len(a.chain.calls), 2 if action == "test" else 1)
                self.assertEqual(a.notifications, [])

    def test_read_snapshots_options_and_pins_successful_voice(self):
        a = app()
        a.play("One. Two.", None)
        a.change("speed", 0.5, save=False)
        a.change("engine", "Windows", save=False)
        a._prepare_selection("ar-SA")
        self.assertEqual(a.chain.prepared, [])
        a.chain.last = "Edge"  # the first unit successfully fell back before speech
        a.chain.calls[0][3]()
        a.chain.calls[0][2](None)
        pump(a)
        self.assertEqual(a.chain.calls[1][4:], ("Edge", 1.0))
        a.chain.calls[1][2](None)
        pump(a)
        self.assertEqual((a.chain.only, a.chain.engines[0].speed), ("Windows", 0.5))

    def test_previous_unit_callbacks_cannot_advance_or_overwrite_current_unit(self):
        a = app()
        a.play("One. Two. Three.", None)
        old = a.chain.calls[0]
        old[2](None)
        pump(a)
        a.chain.calls[1][3]()
        pump(a)
        old[3]()
        old[2](RuntimeError("late"))
        pump(a)
        self.assertEqual((a.popup.caption, len(a.chain.calls), a.notifications), ("Two.", 2, []))

    def test_prepare_is_opt_in_and_new_selection_replaces_exact_first_text(self):
        a = app()
        a.popup.playing = False
        a._handle("show", "First selection. More.", 1, 1)
        self.assertEqual(a.chain.prepared, [("en-US", None)])
        a.cfg["prefetch"] = a.chain.prefetch = True
        a._handle("show", "Different selection! Again.", 1, 1)
        self.assertEqual(a.chain.prepared[-1], ("en-US", "Different selection!"))
        a.play(a.popup.text, None)
        self.assertEqual(a.chain.calls[-1][0], "Different selection!")

    def test_caption_preferences_redraw_without_another_speech_request(self):
        a = app()
        a.cfg.update(caption_font_size=10, caption_background=False, caption_background_opacity=0.6)
        a.play("One. Two.", None)
        a.chain.calls[0][3]()
        pump(a)
        a.pause()
        a.change("caption_font_size", 18, save=False)
        a.change("caption_background", True, save=False)
        a.change("caption_background_opacity", 0.3, save=False)
        self.assertEqual(a.popup.appearance, (18, True, 0.3))
        self.assertEqual((a.popup.caption, a.popup.paused, len(a.chain.calls)), ("One.", True, 1))

    def test_error_stops_the_selection_without_replaying_and_reports_once(self):
        a = app()
        a.play("One. Two.", None)
        a.chain.calls[0][3]()
        a.chain.calls[0][2](RuntimeError("speech failed"))
        pump(a)
        self.assertEqual((a.popup.caption, len(a.chain.calls), len(a.notifications)), ("", 1, 1))


class WindowsPause(unittest.TestCase):
    def test_stop_before_speak_while_paused_never_submits_text_to_sapi(self):
        connecting, release, made_voice, done = (threading.Event() for _ in range(4))
        spoken = []
        token = SimpleNamespace(GetDescription=lambda: "Microsoft Zira")
        tokens = SimpleNamespace(Count=1, Item=lambda i: token)
        category = SimpleNamespace(SetId=lambda *args: None, EnumerateTokens=lambda: tokens)
        voice = SimpleNamespace(Speak=lambda *args: spoken.append(args), WaitUntilDone=lambda ms: True)

        def create(name):
            if name.endswith("SpObjectTokenCategory"):
                connecting.set()
                release.wait(2)
                return category
            made_voice.set()
            return voice

        e = SapiEngine()
        with patch("select_to_tts.engines.comtypes.CoInitialize"), patch("select_to_tts.engines.comtypes.client.CreateObject", side_effect=create):
            e.speak("Never spoken", "en-US", lambda err: done.set())
            self.assertTrue(connecting.wait(2))
            e.pause()
            release.set()
            self.assertTrue(made_voice.wait(2))
            self.assertFalse(done.wait(0.1))
            self.assertEqual(spoken, [])
            e.stop()
            self.assertTrue(done.wait(2))
            self.assertEqual(spoken, [])


class Sentences(unittest.TestCase):
    def test_punctuation_quotes_paragraphs_and_multilingual_text_keep_source_order(self):
        cases = [
            ('One. "Two!" Three?', ['One.', '"Two!"', 'Three?']),
            ('Value 3.14 stays.\n\nNo punctuation\n\nLast', ['Value 3.14 stays.', 'No punctuation', 'Last']),
            ('שלום עולם. English! مرحبا؟\n\nסוף', ['שלום עולם.', 'English!', 'مرحبا؟', 'סוף']),
            ('Dr. Smith reads e.g. this.', ['Dr.', 'Smith reads e.g.', 'this.']),
            ('No punctuation at all', ['No punctuation at all']),
            (' \n\n\t ', []),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                actual = sentences.split(source)
                self.assertEqual(actual, expected)
                self.assertEqual(''.join(c for u in actual for c in u if not c.isspace()),
                                 ''.join(c for c in source if not c.isspace()))


if __name__ == "__main__":
    unittest.main()
