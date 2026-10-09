"""Time from Play to first audio for Edge, silent (nothing is played).

uv run python spikes/edge_latency.py [-n 10] [--speed 1.25] [--prefetch | --legacy]
  --prefetch  prepare() the text, wait 1.5 s like a mouse trip to the button, then speak()
  --legacy    the old wait: download the whole MP3 before anything plays
"""
import argparse
import asyncio
import os
import statistics
import tempfile
import threading
import time

import edge_tts

from codex_speak import lang
from codex_speak.engines import EdgeEngine

TEXT = ("The quick brown fox jumps over the lazy dog. " * 17)[:730]


class Silent:
    def __init__(self, *args):
        self.pending, self.active = False, True

    def write(self, pcm):
        pass

    def close(self):
        pass


class Quiet(EdgeEngine):
    Player = Silent


def rate(speed):
    return f"{round((speed - 1) * 100):+d}%"


def streamed(prefetch, speed):
    e, heard, t0 = Quiet(), threading.Event(), [0.0]
    e.speed = speed
    if prefetch:
        e.prepare("en-US", TEXT)
        time.sleep(1.5)
    t0[0] = time.monotonic()
    first = []
    e.speak(TEXT, "en-US", lambda err: heard.set(), lambda: (first.append(time.monotonic() - t0[0]), heard.set()))
    heard.wait(30)
    e.stop()
    return first[0] if first else None


def legacy(speed):
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        t0 = time.monotonic()
        asyncio.run(edge_tts.Communicate(TEXT, lang.LANGS["en-US"][1], rate=rate(speed)).save(path))
        return time.monotonic() - t0
    finally:
        os.remove(path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=10)
    ap.add_argument("--speed", type=float, default=1.25)
    ap.add_argument("--prefetch", action="store_true")
    ap.add_argument("--legacy", action="store_true")
    a = ap.parse_args()
    mode = "legacy (whole download)" if a.legacy else "prefetch" if a.prefetch else "streamed"
    times = []
    for i in range(a.n):
        t = legacy(a.speed) if a.legacy else streamed(a.prefetch, a.speed)
        print(f"run {i + 1}: {'no audio' if t is None else f'{t:.2f}s'}")
        times.append(t)
    ok = [t for t in times if t is not None]
    if not ok:
        raise SystemExit("no run produced audio")
    print(f"\n{mode}: {len(ok)}/{a.n} runs with audio, median {statistics.median(ok):.2f}s, max {max(ok):.2f}s")
    for limit in (0.3, 1.5, 3.0):
        print(f"  <= {limit}s: {sum(t <= limit for t in ok)}/{a.n}")
