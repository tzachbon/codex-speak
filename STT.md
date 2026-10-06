# Subscription speech-to-text

The same module serves Python callers and other apps on this Windows PC.
It uses the existing Codex ChatGPT login, with no OpenAI API key. Audio goes
to Codex's remote realtime service. The HTTP listener itself is localhost only.

## Run the server

From this project's directory:

```powershell
.venv\Scripts\python.exe -m select_to_tts.stt_server
```

The default port is 18765. Binding fails if another service already owns it.
Keep that process running. Ctrl+C stops accepting requests and waits for active
transcription to finish. It does not install a service or start automatically.

Open `%LOCALAPPDATA%\select-to-tts\stt-connection.json` and copy `base_url` into
OpenWhispr's **Speech-to-Text → Self-Hosted → Server URL**. Set **Model** to
`codex-realtime` (or leave it empty). No API key is needed in that panel.

The URL includes a random local access token. It changes each time the server
starts, so recopy it after a restart. Keep the connection file private. The
server removes its connection file on normal shutdown and does not log URLs,
recordings, or transcripts. `--port` and `--connection-file` can override defaults.

## Internal Python use

```python
from pathlib import Path
from select_to_tts.stt import transcribe

# Blocking call: run in a worker thread, not the GUI thread.
text = transcribe(Path("recording.webm").read_bytes())
```

There is no microphone capture or new UI in the existing TTS app. The module is
ready for its callers to supply a recording.

## HTTP contract

- `GET {base_url}/models` lists `codex-realtime`, a local adapter name, not a selectable OpenAI model.
- `POST {base_url}/audio/transcriptions` takes multipart `file`, optional `model`,
  `language`, `prompt`, and `response_format` (`json` or `text`).
- Default response: `{"text": "transcribed words"}`. Other formats and fields
  are rejected. `language` and `prompt` are advisory hints, not verified controls
  over the input-transcription engine.
- WAV, WebM, Ogg, MP3, MP4/M4A, and FLAC are decoded in memory. Maximum encoded
  audio: 25 MiB. Maximum decoded duration: 60 seconds. One transcription at a time.
- Busy requests receive 429. Bad audio/form fields receive 400, oversized HTTP
  uploads 413, backend failures 502, and backend timeouts 504.
- Native requests and Electron's `Origin: null` are accepted only with the private
  URL and a local Host header. Arbitrary browser origins are rejected.

This matches [OpenWhispr's documented self-hosted request format](https://github.com/OpenWhispr/openwhispr/blob/main/examples/custom-asr-shim/README.md).
An actual OpenWhispr dictation session is a separate acceptance check.

## Limits and verification

This is experimental Codex WebRTC v3, tested with Codex 0.160.1. Audio is sent in
real time. A fixed 12-second tail collects transcript fragments, without a verified
final-transcript signal. Late fragments can be missed. Do not use it for long
recordings or as a guaranteed verbatim transcription service.

The original synthetic English probe had 0% word errors. Mixed Hebrew/English
had 33%, including unwanted transliteration. Real microphone/noisy speech is
not validated. There is no silent fallback to a different provider.

Run deterministic checks:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p test_stt.py -v
```

Explicit live HTTP check, using the existing synthetic English fixture under
`spikes/out` (consumes subscription usage):

```powershell
$env:STT_LIVE_CHECK = '1'
.venv\Scripts\python.exe -m unittest discover -s tests -p test_stt.py -v
Remove-Item Env:\STT_LIVE_CHECK
```

The live check encodes the fixture as WebM, uploads it over HTTP, and compares
the returned transcript to the reference only after receiving the result.
