import unittest

from pynput.mouse import Button

from select_to_tts import clipboard, lang
from select_to_tts.audio import NoAudioError
from select_to_tts.engines import Chain
from select_to_tts.trigger import SelectionTrigger


class Lang(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(lang.detect("שלום עולם"), "he-IL")
        self.assertEqual(lang.detect("hello world"), "en-US")
        self.assertEqual(lang.detect("שלום hello עולם"), "he-IL")
        self.assertEqual(lang.detect("Привет мир"), "ru-RU")
        self.assertEqual(lang.detect("مرحبا بالعالم"), "ar-SA")
        self.assertEqual(lang.detect("123"), "en-US")


class Clipboard(unittest.TestCase):
    def test_safe_to_borrow(self):
        self.assertTrue(clipboard.safe_to_borrow(set()))
        self.assertTrue(clipboard.safe_to_borrow({13, 1, 7, 16, 49353}))  # text + HTML Format
        self.assertTrue(clipboard.safe_to_borrow({2, 8, 17}))  # bitmap backed by a DIB
        self.assertFalse(clipboard.safe_to_borrow({2}))  # bare HBITMAP
        self.assertFalse(clipboard.safe_to_borrow({14, 13}))  # enhanced metafile


class Fake:
    def __init__(self, name, err=None):
        self.name, self.err, self.calls = name, err, 0

    def speak(self, text, tag, on_done):
        self.calls += 1
        on_done(self.err)

    def stop(self):
        pass


class ChainTest(unittest.TestCase):
    def run_chain(self, *engines, only=None):
        chain, result = Chain(list(engines)), []
        chain.only = only
        chain.speak("hi", None, result.append)
        return chain, result

    def test_falls_back_only_before_audio(self):
        a, b = Fake("Codex", NoAudioError("x")), Fake("Edge")
        chain, result = self.run_chain(a, b)
        self.assertEqual((result, chain.last, b.calls), ([None], "Edge", 1))

    def test_mid_playback_failure_is_reported_not_retried(self):
        a, b = Fake("Codex", RuntimeError("cut")), Fake("Edge")
        chain, result = self.run_chain(a, b)
        self.assertEqual((type(result[0]), b.calls), (RuntimeError, 0))

    def test_only_never_touches_other_engines(self):
        a, b = Fake("Codex"), Fake("Windows", NoAudioError("x"))
        chain, result = self.run_chain(a, b, only="Windows")
        self.assertEqual((a.calls, type(result[0])), (0, NoAudioError))


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


if __name__ == "__main__":
    unittest.main()
