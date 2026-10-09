"""Edge TTS audio, decoded to 24 kHz mono 16-bit PCM while it is still downloading."""
import asyncio
import collections
import threading

import av


class EdgeStream:
    """Consumes an async iterator of MP3 chunks on its own thread. `read` hands out the PCM as it appears."""

    def __init__(self, chunks):
        self._pcm, self._cond = collections.deque(), threading.Condition()
        self._cancelled, self.done, self.error = threading.Event(), False, None
        threading.Thread(target=self._run, args=(chunks,), daemon=True).start()

    def _run(self, chunks):
        try:
            asyncio.run(self._pump(chunks))
        except Exception as e:
            self.error = e
        finally:
            with self._cond:
                self.done = True
                self._cond.notify_all()

    async def _pump(self, chunks):
        dec = av.CodecContext.create("mp3", "r")
        rs = av.AudioResampler(format="s16", layout="mono", rate=24000)
        try:
            async for data in chunks:
                if self._cancelled.is_set():
                    return
                self._decode(dec, rs, dec.parse(data))
            self._decode(dec, rs, [*dec.parse(None), None])  # None drains the decoder
            self._add(rs.resample(None))
        finally:
            await chunks.aclose()  # closes the Edge connection now, not at garbage collection

    def _decode(self, dec, rs, packets):
        for packet in packets:
            for frame in dec.decode(packet):
                self._add(rs.resample(frame))

    def _add(self, frames):
        pcm = b"".join(bytes(f.planes[0])[: f.samples * 2] for f in frames)
        if pcm:
            with self._cond:
                self._pcm.append(pcm)
                self._cond.notify_all()

    def read(self, stop):
        """PCM chunks until the request ends or `stop` is set. Raises the request's error afterwards."""
        while True:
            with self._cond:
                while not self._pcm and not self.done and not stop.is_set():
                    self._cond.wait(0.05)
                if stop.is_set():
                    return
                if self._pcm:
                    pcm = self._pcm.popleft()
                elif self.done and self.error:
                    raise self.error
                else:
                    return
            yield pcm

    def cancel(self):
        self._cancelled.set()
