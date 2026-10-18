import array
import threading
import unittest
from unittest import mock

from codex_speak import audio
from codex_speak.audio import PcmPlayer


class Player(unittest.TestCase):
    def test_drain_waits_until_the_output_start_notification_has_been_sent(self):
        p = PcmPlayer.__new__(PcmPlayer)
        p._buf, p._lock, p._width, p._paused = bytearray(), threading.Lock(), 2, threading.Event()
        pending_when_output_is_filled, heard = [], []

        class Output(bytearray):
            def __setitem__(self, key, value):
                pending_when_output_is_filled.append(p.pending)
                super().__setitem__(key, value)

        p.arm(lambda: heard.append(1))
        p.write(array.array("h", [1000] * 4).tobytes())
        p._fill(Output(8), 4, None, None)
        self.assertTrue(all(pending_when_output_is_filled))
        self.assertEqual((p.pending, heard), (False, [1]))

    def test_start_waits_for_voiced_unpaused_output_and_fires_once(self):
        p = PcmPlayer.__new__(PcmPlayer)
        p._buf, p._lock, p._width, p._paused = bytearray(), threading.Lock(), 2, threading.Event()
        heard, out = [], bytearray(8)
        p.arm(lambda: heard.append(1))
        p.write(bytes(8))  # warmup silence is not speech
        p._fill(out, 4, None, None)
        self.assertFalse(heard)
        p._paused.set()
        p.write(array.array("h", [1000] * 8).tobytes())
        p._fill(out, 4, None, None)
        self.assertEqual((heard, bytes(out), len(p._buf)), ([], bytes(8), 16))
        p._paused.clear()
        p._fill(out, 4, None, None)
        p._fill(out, 4, None, None)
        self.assertEqual(heard, [1])

    def test_paused_player_plays_silence_and_keeps_the_queue(self):
        paused = threading.Event()
        p = PcmPlayer.__new__(PcmPlayer)  # no sound device: drive the callback directly
        p._buf, p._lock, p._width, p._paused = bytearray(b"\x01\x02" * 8), threading.Lock(), 2, paused
        p._on_audio = None
        out = bytearray(8)
        paused.set()
        p._fill(out, 4, None, None)
        self.assertEqual((bytes(out), len(p._buf)), (bytes(8), 16))
        paused.clear()
        p._fill(out, 4, None, None)
        self.assertEqual((bytes(out), len(p._buf)), (b"\x01\x02" * 4, 8))


def _pcm(level, samples=4):
    return array.array("h", [level] * samples).tobytes()


class JitterCushion(unittest.TestCase):
    def player(self, hold, holding=False):
        p = PcmPlayer.__new__(PcmPlayer)  # no sound device: drive the callback directly
        p._buf, p._lock, p._width, p._paused = bytearray(), threading.Lock(), 2, threading.Event()
        p._on_audio, p._hold, p._holding = None, hold, holding
        return p

    def at(self, now, call, *args):
        with mock.patch.object(audio.time, "monotonic", return_value=now):
            return call(*args)

    def fill(self, p, now):
        out = bytearray(8)
        self.at(now, p._fill, out, 4, None, None)
        return bytes(out)

    def test_waits_for_a_cushion_then_plays(self):
        p = self.player(16, holding=True)
        self.at(10.0, p.write, _pcm(1000))
        self.assertEqual(self.fill(p, 10.01), bytes(8))
        self.at(10.02, p.write, _pcm(1000))
        self.assertEqual(self.fill(p, 10.03), _pcm(1000))

    def test_a_callback_before_the_first_write_keeps_the_cushion(self):
        p = self.player(16, holding=True)
        self.assertEqual(self.fill(p, 10.0), bytes(8))
        self.at(10.01, p.write, _pcm(1000))
        self.assertEqual(self.fill(p, 10.02), bytes(8))

    def test_plays_the_tail_once_the_writes_end(self):
        p = self.player(16, holding=True)
        self.at(10.0, p.write, _pcm(1000))
        self.assertEqual(self.fill(p, 10.0 + audio.JITTER), _pcm(1000))

    def test_lengthens_pauses_but_not_speech_to_rebuild_the_cushion(self):
        p = self.player(32)
        self.at(10.0, p.write, _pcm(10) + _pcm(1000))
        self.assertEqual((self.fill(p, 10.01), len(p._buf)), (bytes(8), 16))
        del p._buf[:8]
        self.assertEqual((self.fill(p, 10.02), len(p._buf)), (_pcm(1000), 0))

    def test_running_dry_waits_for_a_new_cushion(self):
        p = self.player(16)
        self.at(10.0, p.write, _pcm(1000))
        self.assertEqual(self.fill(p, 10.01), _pcm(1000))
        self.assertEqual(self.fill(p, 10.02), bytes(8))  # a late packet
        self.at(10.03, p.write, _pcm(1000))
        self.assertEqual(self.fill(p, 10.04), bytes(8))


if __name__ == "__main__":
    unittest.main()
