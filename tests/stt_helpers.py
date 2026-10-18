"""Shared fixtures for the speech-to-text tests."""
import asyncio
import sys
from http.client import HTTPConnection
import io
import json
import os
import queue
import tempfile
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import wave

import av

from harness_discussion import stt, stt_server
from harness_discussion.codex_rt import AppServer


def wav(seconds=0.1):
    output = io.BytesIO()
    with wave.open(output, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\0\0" * int(24000 * seconds))
    return output.getvalue()


class FakePeer:
    """Stands in for aiortc: always connected, pulls frames from the track, and plays scripted events."""
    connectionState = "connected"
    localDescription = MagicMock(sdp="")

    def __init__(self, script):
        self.script, self.handler = script, None

    def addTrack(self, track):
        self.track = track

    def createDataChannel(self, name):
        peer = self
        class Channel:
            def on(self, event):
                def register(handler):
                    peer.handler = handler
                    return handler
                return register
        return Channel()

    async def createOffer(self):
        return None

    async def setLocalDescription(self, description):
        pass

    async def close(self):
        pass

    async def play(self):
        while not self.track.finished_at:
            await self.track.recv()
        for delay, event in self.script:  # Delays are seconds after the audio finished sending.
            await asyncio.sleep(delay)
            self.handler(json.dumps(event(self.track)))


def receive(script, seconds=2.0):
    """Runs _receive against FakePeer. Returns (text or SttError, diag)."""
    peer, diag = FakePeer(script), {"started": time.monotonic(), "stage": "connect", "marks": {}, "events": {}}
    srv = MagicMock(alive=True, events=queue.Queue())
    async def run():
        player = None
        with patch.object(stt, "RTCPeerConnection", return_value=peer):
            task = asyncio.ensure_future(stt._receive(srv, b"\0\0" * int(stt.RATE * seconds), "", "", diag))
            await asyncio.sleep(0)
            player = asyncio.ensure_future(peer.play())
            try:
                return await task
            except stt.SttError as error:
                return error
            finally:
                player.cancel()
    return asyncio.run(run()), diag


def words(text, end_ms):
    return lambda track: {"type": "input_transcript.added", "item": {"text": text}, "end_ms": end_ms(track)}


def multipart(audio, **fields):
    body = b'--probe\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n' + audio + b"\r\n"
    for name, value in fields.items():
        body += f'--probe\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    return body + b"--probe--\r\n"
