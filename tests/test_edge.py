import io
import threading
import time
import unittest

import av

from codex_speak.__main__ import App
from codex_speak.audio import NoAudioError
from codex_speak.edge_stream import EdgeStream
from codex_speak.engines import Chain, EdgeEngine


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

    def test_a_read_that_was_stopped_hands_out_nothing_more(self):
        stream = EdgeStream(agen(list(pieces(tone_mp3()))))
        time.sleep(0.3)  # everything is buffered
        stop = threading.Event()
        stop.set()
        self.assertEqual(list(stream.read(stop)), [])

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

    def arm(self, on_audio):
        self.on_audio = on_audio

    def write(self, pcm):
        self.writes.append(pcm)
        if not self.paused.is_set() and getattr(self, "on_audio", None):
            on_audio, self.on_audio = self.on_audio, None
            on_audio()

    def close(self):
        self.closed = True


def engine(source, player=FakePlayer):
    class Fake(EdgeEngine):
        Player = player
        requests = []

        def _source(self, text, voice, rate):
            self.requests.append((text, voice, rate))
            return source()
    Fake.requests = []
    FakePlayer.opened = []
    return Fake()


def speak(e, text="hello"):
    done, heard = threading.Event(), []
    result = []
    e.speak(text, "en-US", lambda err: (result.append(err), done.set()), lambda: heard.append(time.monotonic()))
    return done, result, heard


class EdgeEngineReads(unittest.TestCase):
    def test_receiving_pcm_while_paused_does_not_report_playback(self):
        release = threading.Event()
        data = tone_mp3()
        expected = decode_whole(data) * 2

        class HeldPlayer(FakePlayer):
            def write(self, pcm):
                self.writes.append(pcm)
                self.pending = True

            def consume(self):
                self.pending = False
                self.on_audio()
                self.on_audio = None

        async def source():
            while not release.is_set():
                await __import__("asyncio").sleep(0.01)
            for chunk in pieces(data):
                yield chunk

        e = engine(source, player=HeldPlayer)
        done, result, heard = speak(e)
        e.pause()
        release.set()
        deadline = time.monotonic() + 5
        while (not FakePlayer.opened or sum(map(len, FakePlayer.opened[0].writes)) < expected) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(FakePlayer.opened[0].writes)
        self.assertEqual(heard, [])
        e.resume()
        FakePlayer.opened[0].consume()
        self.assertTrue(done.wait(5))
        self.assertEqual((result, len(heard)), ([None], 1))

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


class EdgePrefetch(unittest.TestCase):
    def read(self, e, text="hello", tag="en-US"):
        done = threading.Event()
        e.speak(text, tag, lambda err: done.set())
        self.assertTrue(done.wait(5))

    def test_a_matching_prefetch_is_joined_with_no_second_request(self):
        e = engine(lambda: agen(list(pieces(tone_mp3()))))
        e.prepare("en-US", "hello")
        time.sleep(0.3)
        self.assertEqual(FakePlayer.opened, [])  # nothing plays before ▶
        self.read(e)
        self.assertEqual(len(e.requests), 1)
        self.assertTrue(FakePlayer.opened[0].writes)

    def test_pressing_play_right_after_prepare_joins_the_download_in_progress(self):
        data = list(pieces(tone_mp3(2.0)))

        async def slow():
            for chunk in data:
                yield chunk
                await __import__("asyncio").sleep(0.01)
        e = engine(slow)
        e.prepare("en-US", "hello")
        self.read(e)  # no wait: the request has barely started
        written = sum(len(w) for p in FakePlayer.opened for w in p.writes) // 2
        self.assertEqual((len(e.requests), written), (1, decode_whole(b"".join(data))))

    def test_a_different_text_voice_or_speed_starts_a_new_request(self):
        for change in ("text", "voice", "speed"):
            e = engine(lambda: agen(list(pieces(tone_mp3()))))
            e.prepare("en-US", "hello")
            if change == "speed":
                e.speed = 1.25
            self.read(e, "other" if change == "text" else "hello", "he-IL" if change == "voice" else "en-US")
            self.assertEqual(len(e.requests), 2, change)

    def test_stop_drops_a_prefetch(self):
        e = engine(lambda: agen(list(pieces(tone_mp3()))))
        e.prepare("en-US", "hello")
        e.stop()
        self.read(e)
        self.assertEqual(len(e.requests), 2)

    def test_a_new_prefetch_replaces_the_old_one(self):
        e = engine(lambda: agen(list(pieces(tone_mp3()))))
        e.prepare("en-US", "first")
        e.prepare("en-US", "second")
        self.read(e, "second")
        self.assertEqual([r[0] for r in e.requests], ["first", "second"])

    def test_speaking_without_a_prefetch_makes_one_request(self):
        e = engine(lambda: agen(list(pieces(tone_mp3()))))
        self.read(e)
        self.assertEqual(len(e.requests), 1)

    def test_prepare_without_text_only_drops(self):
        e = engine(lambda: agen(list(pieces(tone_mp3()))))
        e.prepare("en-US", "hello")
        e.prepare("en-US")
        self.read(e)
        self.assertEqual(len(e.requests), 2)


def blocking(closed):
    """A request that never finishes; `closed` is set when something closes it."""
    async def source():
        try:
            while True:
                await __import__("asyncio").sleep(0.02)
                yield b""
        finally:
            closed.set()
    return source


class EdgeCleanup(unittest.TestCase):
    def test_a_read_replaced_before_it_started_does_not_leave_its_request_running(self):
        closed = {"A": threading.Event(), "B": threading.Event()}

        class Two(EdgeEngine):
            Player = FakePlayer

            def _source(self, text, voice, rate):
                return blocking(closed[text])()
        e = Two()
        e._busy.acquire()  # an earlier read is still shutting down, so neither worker has started
        e.speak("A", "en-US", lambda err: None)
        e.speak("B", "en-US", lambda err: None)
        e._busy.release()
        self.assertTrue(closed["A"].wait(3))
        e.stop()
        self.assertTrue(closed["B"].wait(3))

    def test_a_failed_prefetch_is_retried_when_play_is_pressed(self):
        calls = []

        def source():
            calls.append(1)
            return agen([], then=RuntimeError("offline")) if len(calls) == 1 else agen(list(pieces(tone_mp3())))
        e = engine(source)
        e.prepare("en-US", "hello")
        deadline = time.monotonic() + 5
        while not e._pre[1].done and time.monotonic() < deadline:
            time.sleep(0.01)
        done, result, _ = speak(e)
        self.assertTrue(done.wait(5))
        self.assertEqual((result, len(calls)), ([None], 2))

    def test_a_speed_change_that_hands_the_read_to_another_engine_drops_the_edge_prefetch(self):
        closed = threading.Event()

        class Codexish:
            name, speed, max_speed = "Codex", 1.25, 1.0

            def prepare(self, lang_tag, text=None):
                pass
        edge = engine(blocking(closed))
        edge.speed = 1.25
        chain = Chain([Codexish(), edge])
        chain.prefetch = True
        chain.prepare("en-US", "hello")  # speed 1.25: Edge is first and prefetches
        time.sleep(0.2)
        self.assertFalse(closed.is_set())
        chain.engines[0].speed = edge.speed = 1.0  # speed 1.0: Codex is first
        chain.prepare("en-US", "hello")
        self.assertTrue(closed.wait(3))


class Prep:
    speed, name = 1.0, "Prep"

    def __init__(self):
        self.prepared = []

    def prepare(self, lang_tag, text=None):
        self.prepared.append((lang_tag, text))


class ChainPrefetch(unittest.TestCase):
    def test_auto_preparation_preserves_codex_inference_and_fallback_language(self):
        codex, edge = Prep(), Prep()
        codex.name, edge.name = "Codex", "Edge"
        chain = Chain([codex, edge])
        chain.prefetch = True
        chain.prepare(None, "Hello.", fallback_tag="he-IL")
        chain.only = "Edge"
        chain.prepare(None, "Hello.", fallback_tag="he-IL")
        chain.prepare("es-ES", "Hola.", fallback_tag="en-US")
        self.assertEqual(codex.prepared, [(None, "Hello.")])
        self.assertEqual(edge.prepared, [("he-IL", "Hello."), ("es-ES", "Hola.")])

    def test_text_reaches_the_first_engine_only_when_prefetch_is_on(self):
        a = Prep()
        chain = Chain([a])
        chain.prepare("he-IL", "shalom")
        chain.prefetch = True
        chain.prepare("he-IL", "shalom")
        self.assertEqual(a.prepared, [("he-IL", None), ("he-IL", "shalom")])


class ReadLog(unittest.TestCase):
    def logged(self, hear):
        app = App.__new__(App)  # no window: only the log line is under test
        app.chain, app.cfg = Chain([]), {"speed": 1.25}
        app.chain.last = "Edge"
        done, heard = app._logged("secret words", lambda err: None)
        with self.assertLogs("codex_speak", "INFO") as logs:
            hear and heard()
            done(None)
        return logs.output[0]

    def test_the_read_line_has_the_first_audio_time_and_never_the_text(self):
        line = self.logged(hear=True)
        self.assertRegex(line, r"read 12 chars with Edge in [\d.]+s \(first audio [\d.]+s\) at 1.25x, error: None")
        self.assertNotIn("secret", line)

    def test_a_read_that_never_made_a_sound_logs_a_dash(self):
        self.assertIn("(first audio -)", self.logged(hear=False))


if __name__ == "__main__":
    unittest.main()
