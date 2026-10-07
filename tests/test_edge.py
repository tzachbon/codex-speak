import io
import threading
import time
import unittest

import av

from select_to_tts.audio import NoAudioError
from select_to_tts.edge_stream import EdgeStream
from select_to_tts.engines import EdgeEngine


def tone_mp3(seconds=1.0, rate=24000):
    """A real MP3 (440 Hz, mono) so decoding is checked against known-good bytes."""
    import array
    import math
    samples = array.array("h", (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(int(seconds * rate))))
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp3", options={"id3v2_version": "0", "write_xing": "0"}) as out:  # raw frames, like Edge sends
        stream = out.add_stream("mp3", rate=rate, layout="mono")
        frame = av.AudioFrame(format="s16", layout="mono", samples=len(samples))
        frame.sample_rate = rate
        frame.planes[0].update(samples.tobytes())
        for packet in stream.encode(frame):
            out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


def decode_whole(data):
    rs, total = av.AudioResampler(format="s16", layout="mono", rate=24000), 0
    with av.open(io.BytesIO(data)) as c:
        for frame in c.decode(audio=0):
            total += sum(o.samples for o in rs.resample(frame))
        total += sum(o.samples for o in rs.resample(None))
    return total


def pieces(data, sizes=(417, 1000, 33)):
    i = 0
    while i < len(data):
        for size in sizes:
            yield data[i:i + size]
            i += size


async def agen(chunks, then=None):
    for chunk in chunks:
        yield chunk
    if then:
        raise then


class EdgeStreamTests(unittest.TestCase):
    def test_chunked_decode_matches_decoding_the_whole_file(self):
        data = tone_mp3()
        pcm = b"".join(EdgeStream(agen(pieces(data))).read(threading.Event()))
        self.assertEqual(len(pcm) // 2, decode_whole(data))
        self.assertGreater(max(memoryview(pcm).cast("h")), 1000)  # speech-level signal, not silence

    def test_error_after_audio_is_raised_once_the_audio_is_read(self):
        data = tone_mp3()
        stream = EdgeStream(agen(list(pieces(data))[:6], then=RuntimeError("boom")))
        got = []
        with self.assertRaisesRegex(RuntimeError, "boom"):
            for pcm in stream.read(threading.Event()):
                got.append(pcm)
        self.assertTrue(got)

    def test_error_before_audio_is_raised_on_the_first_read(self):
        stream = EdgeStream(agen([], then=RuntimeError("no network")))
        with self.assertRaisesRegex(RuntimeError, "no network"):
            next(stream.read(threading.Event()))

    def test_stop_ends_a_read_that_is_waiting_for_audio(self):
        async def never():
            await __import__("asyncio").sleep(30)
            yield b""
        stop, out = threading.Event(), []
        reader = threading.Thread(target=lambda: out.extend(EdgeStream(never()).read(stop)))
        reader.start()
        time.sleep(0.2)
        stop.set()
        reader.join(2)
        self.assertFalse(reader.is_alive())

    def test_cancel_stops_consuming_the_request(self):
        pulled = []

        async def slow():
            for i in range(50):
                pulled.append(i)
                yield b"\x00" * 10
                await __import__("asyncio").sleep(0.02)
        stream = EdgeStream(slow())
        time.sleep(0.1)
        stream.cancel()
        time.sleep(0.2)
        count = len(pulled)
        time.sleep(0.2)
        self.assertEqual(len(pulled), count)
        self.assertLess(count, 50)


class FakePlayer:
    """Stands in for PcmPlayer: no sound device, writes are consumed at once."""
    opened = []

    def __init__(self, rate, channels, paused):
        self.rate, self.paused, self.writes, self.closed = rate, paused, [], False
        self.pending, self.active = False, True
        FakePlayer.opened.append(self)

    def write(self, pcm):
        self.writes.append(pcm)

    def close(self):
        self.closed = True


def engine(source, player=FakePlayer):
    class Fake(EdgeEngine):
        Player = player

        def _source(self, text, voice, rate):
            return source()
    FakePlayer.opened = []
    return Fake()


def speak(e, text="hello"):
    done, heard = threading.Event(), []
    result = []
    e.speak(text, "en-US", lambda err: (result.append(err), done.set()), lambda: heard.append(time.monotonic()))
    return done, result, heard


class EdgeEngineReads(unittest.TestCase):
    def test_audio_is_reported_at_the_first_chunk_while_the_request_is_still_running(self):
        data, release = list(pieces(tone_mp3())), threading.Event()

        async def source():
            for chunk in data[:6]:
                yield chunk
            while not release.is_set():
                await __import__("asyncio").sleep(0.01)
            for chunk in data[6:]:
                yield chunk
        e = engine(source)
        done, result, heard = speak(e)
        deadline = time.monotonic() + 3
        while not heard and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual((len(heard), done.is_set()), (1, False))
        release.set()
        self.assertTrue(done.wait(5))
        self.assertEqual((result, len(heard)), ([None], 1))
        self.assertTrue(FakePlayer.opened[0].closed)

    def test_failure_before_any_audio_lets_the_chain_fall_through(self):
        done, result, heard = speak(engine(lambda: agen([], then=RuntimeError("offline"))))
        self.assertTrue(done.wait(5))
        self.assertIsInstance(result[0], NoAudioError)
        self.assertFalse(heard)

    def test_an_empty_stream_is_a_failure_before_audio(self):
        done, result, _ = speak(engine(lambda: agen([])))
        self.assertTrue(done.wait(5))
        self.assertIsInstance(result[0], NoAudioError)

    def test_failure_after_audio_started_is_not_retried_on_another_engine(self):
        data = list(pieces(tone_mp3()))[:6]
        done, result, heard = speak(engine(lambda: agen(data, then=RuntimeError("dropped"))))
        self.assertTrue(done.wait(5))
        self.assertEqual((type(result[0]), len(heard)), (RuntimeError, 1))

    def test_a_missing_sound_device_is_a_failure_before_audio(self):
        class NoDevice:
            def __init__(self, *a):
                raise OSError("no device")
        done, result, heard = speak(engine(lambda: agen(list(pieces(tone_mp3()))), player=NoDevice))
        self.assertTrue(done.wait(5))
        self.assertIsInstance(result[0], NoAudioError)
        self.assertFalse(heard)

    def test_stop_while_waiting_for_the_first_audio_ends_quietly(self):
        async def source():
            await __import__("asyncio").sleep(30)
            yield b""
        e = engine(source)
        done, result, heard = speak(e)
        time.sleep(0.2)
        e.stop()
        self.assertTrue(done.wait(2))
        self.assertEqual((result, heard, FakePlayer.opened), ([None], [], []))

    def test_the_player_follows_the_engines_pause_state(self):
        e = engine(lambda: agen(list(pieces(tone_mp3()))))
        done, _, _ = speak(e)
        self.assertTrue(done.wait(5))
        self.assertIs(FakePlayer.opened[0].paused, e.paused)


if __name__ == "__main__":
    unittest.main()
