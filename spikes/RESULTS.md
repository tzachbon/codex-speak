# T1 results: Codex realtime feasibility (PROTOTYPE)

Run 2026-10-06, codex-cli 0.160.1, ChatGPT login (plan `pro`), no API key. 24 runs: 2 strategies × 4 fixtures × 3.
Reproduce: `uv run --group spike python spikes/realtime_probe.py`. Per-run data is in `spikes/out/results.json` (git-ignored).

## Verdict: PASS with strategy S2. Codex is the primary engine.

| Strategy | WER ≤ 0.05 | Median first audio | Max first audio | Failures |
| --- | --- | --- | --- | --- |
| S1 `appendSpeech` | 9/12 | 1.00 s | 1.49 s | he#2 dropped the last sentence, en#2 stopped after sentence 1, numbers#2 produced no speech |
| **S2 `appendText` role=user + TTS prompt** | **12/12** (all 0.00) | **1.17 s** | 2.33 s | none |

The Hebrew, English, mixed Hebrew/English, and numbers/date/URL fixtures were all read word for word with S2.

## Findings that change PLAN.md

1. **The websocket transport needs an API key.** `thread/realtime/start` without `transport` fails with `realtime conversation requires API key auth` (`codex-rs/core/src/realtime_conversation.rs`, `realtime_api_key`).
2. **WebRTC works with the ChatGPT login.** `transport: {type:"webrtc", sdp}` skips the API-key lookup. It **requires `version: "v3"`**. The default v1 fails with `AVAS requires OpenAI-Alpha: quicksilver=v2`, and v2 is rejected for WebRTC.
3. **Audio comes as a WebRTC Opus track, not `outputAudio/delta`.** The client must run a peer connection: send a silent audio track, open an `oai-events` data channel, apply the answer from `thread/realtime/sdp`, and play the remote track. `aiortc` 1.15.0 handles this on Windows/Python 3.11.
4. **Order of events:** `thread/realtime/started`, then `thread/realtime/sdp`. Append text only after the peer connection reaches `connected`. Appending earlier produced silence.
5. **Completion signal:** `thread/realtime/transcript/done` with `role:"assistant"` carries the full read text. The data channel also emits `turn.done`.
6. **Remote audio** decodes to 24 kHz mono s16 after resampling. The English WAV was 85% voiced with a peak of 18781, so it is real speech, not noise.

## Not yet verified

- **Pronunciation quality of the Hebrew audio by ear.** The user should listen to `spikes/out/he_S2_0.wav` and `spikes/out/mixed_S2_0.wav`.
- **Behavior on texts above about 70 words.**
