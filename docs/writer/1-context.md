## Objective

Add a Snapdraft-style writing feature to Harness Discussion on macOS and Windows. The owner's workflow is:
he either types a draft or dictates one, and both always need a rewrite in a chosen *mode* (Fix errors,
Message, Email, Improve writing, or a custom mode such as "My PR voice"). The rewrite should happen inside
the app he is already typing in, with no panel. A review panel opens only if he asks for it.

Rewrites and transcription use the AI sources the app already detects, in the same order as the voices:
Cursor (desktop sign-in), then Codex (ChatGPT sign-in through `codex app-server`), then the local Qwen3-4B
already used by Summarize. Each source offers a model and a reasoning-effort picker where it supports one.

The same change declutters the floating selection bar, which grows from 11 to 12 controls if Rewrite
is simply added.

## Definition of Done

The work is done when all of the following are true on both a Mac (Apple silicon, macOS 13+) and the
owner's Windows 11 PC (`Tzach-PC`):

1. **In-place rewrite from the bar (E1).** Select text in an editable field in Notes or TextEdit, Slack, and a browser
   `<textarea>` (Mac), and in Notepad, Slack, and a browser `<textarea>` (Windows). The writing bar shows. Choosing a
   mode replaces the selection with the rewrite. The clipboard is unchanged afterwards.
2. **Toast with Undo and Review (E2).** After each in-place rewrite, a toast shows the mode and source with Undo, Review,
   and Mode. Undo restores the original text. Review opens the side-by-side panel (B).
3. **Hotkey rewrite (E3).** The rewrite shortcut rewrites the selection with the default mode. A double press opens the mode menu.
   With nothing selected, a hint appears and nothing else happens.
4. **Dictation (E4).** Holding the dictation shortcut records the microphone. Releasing it transcribes the recording (Codex,
   then Cursor if enabled), rewrites it with the default mode, and types it at the cursor, followed by the same toast.
5. **Sources, models, effort.** Settings → Writing lists Cursor, Codex, and Local in order, each with an on/off toggle, ↑ ↓,
   and model and effort menus where supported. A failing source falls through to the next one.
6. **Decluttered bar.** The bar shows the writing layout for editable selections, the reading layout otherwise, and
   the playing layout during a read, as specified below. Every hidden option is reachable from "…".
7. **Safety.** No paste happens if the frontmost app or the selection changed while the model worked. Password and secure
   fields are never read or replaced. The log never contains the user's text.
8. **Quality gate.** `uv run python -m unittest discover -s tests` passes in CI on `windows-latest` and `macos-latest`.
   The README "What it does", "Where your text goes", and Settings sections describe Writer and Dictation.

## Context and evidence

### What the app is today (verified in this repo, branch `feat/add-snapdraft-harness-discussion`)

- Python 3.11 to 3.13 desktop app. macOS uses PyObjC and AppKit (`src/harness_discussion/mac/`). Windows uses Tk, Win32,
  pynput, and UI Automation (`src/harness_discussion/win/`). Shared logic is in `src/harness_discussion/`.
- `core.App` (in `core.py`) mixes in `Captions, Sources, Updates, Summaries, Skips` and runs an event queue. `_handle(kind, *args)`
  dispatches events such as `"show"`, `"press"`, `"hotkey"`, `"summary"`, and `"statuses"`.
- **Selection bar.** `mac/popup.py` `Popup.__init__` builds this row: Play, spinner, Previous, Next, Stop, Summarize, ai_progress,
  divider, Source, Language, Speed, divider, Settings, Close. Previous, Next, and Stop are dimmed when idle, "so the bar
  keeps its width" (lines 259 to 261). `win/popup.py` mirrors it.
- **Dismissal.** `core.py` lines 325 and 326 hide the bar on an outside click only when nothing is playing. There is no Esc handler.
- **Summarize** (`summarize.py`, `app_summarize.py`): a pinned llama.cpp `llama-server` with Qwen3-4B-Q4_K_M runs on 127.0.0.1.
  It is downloaded once and verified by size and SHA-256, and it stops after 300 s idle. `Server.summarize(text, language)` hardcodes the summary
  prompt and `max_tokens: 400`. The docstring says it downloads "as Snapdraft does".
- **Codex:** `codex_rt.AppServer` drives `codex app-server` over stdio JSON-RPC (`call(method, params)`) and starts an
  `{"ephemeral": true}` thread. The app uses it for the realtime voice (`codex_rt.py`) and for STT (`stt.py`, `transcribe(audio_bytes, language=, prompt=)`,
  max 60 s and 25 MB).
- **Codex text turns (verified with codex-cli 0.163.0 `app-server generate-json-schema`):** `TurnStartParams` accepts `model`,
  `effort` (ReasoningEffort), `outputSchema` (a JSON Schema constraining the final message), `sandboxPolicy`, and `approvalPolicy`.
  `ModelListResponse.Model` has `id`, `displayName`, `isDefault`, `hidden`, `defaultReasoningEffort`, and `supportedReasoningEfforts`.
- **Cursor:** `cursor_tts.py` calls `https://api2.cursor.sh/aiserver.v1.AiService/TextToSpeech` with hand-encoded protobuf and
  the desktop sign-in token (`cursor_auth.token()`). The Cursor desktop bundle (`workbench.desktop.main.js`) also contains
  RPC names `AvailableModels`, `GetUsableModels`, `StreamChat`, `StreamUnifiedChat*`, `TranscribeAudio`, and `SpeechToTextSession`.
  Their request shapes are **not verified**. They are undocumented, like TextToSpeech.
- **Clipboard and selection:** `win/clipboard.py` (`snapshot`, `restore`, `sequence`, `safe_to_borrow`) and
  `mac/pasteboard.py` (`snapshot`, `restore`, `copy_selection`, `safe_to_borrow`) already borrow the clipboard for one copy and restore every format.
  `mac/selection.py` reads through AX (`_via_ax`, `secure_input()`, `_frontmost_pid`). `win/selection.py` reads through UIA and
  the clipboard (`_via_uia`, `_foreground_class` skips terminals).
- **Hotkeys:** `hotkeys.py` parses pynput-style specs. `mac/trigger.HotKey` watches **key-down only**.
  `win/trigger.HotKey` has `_press` and `_release`. Settings default `"hotkey": "<cmd>+<alt>+r"` (Mac) or `"<ctrl>+<alt>+r"`.
- **Settings:** `settings.DEFAULTS` holds flat keys (`sources`, `voices`, `speed`, `hotkey`, and so on) in `settings.json`.
- **Audio:** `sounddevice>=0.5.6` is already a dependency and can record. The Mac `Info.plist` (set in `packaging/build_mac.sh`)
  has **no** `NSMicrophoneUsageDescription`, and `packaging/entitlements.plist` has **no** `com.apple.security.device.audio-input`. A hardened-runtime
  build needs both to record.
- **CI:** `.github/workflows/build.yml` runs the unit tests and builds on `windows-latest` and `macos-latest`.
- **Windows PC:** the owner's T3 shows `Tzach-PC` connected through T3 Connect. The local T3 environment API on the Mac does not list it,
  so threads on it are started from the T3 app.

### Prior-art verification

- **Snapdraft** (github.com/ranyitz/snapdraft, inspected README): a proprietary macOS overlay opened with Cmd+Shift+Space. It has
  rewrite modes (Fix errors, Improve writing, Email, Message, and custom modes), keeps formatting, dictates with whisper.cpp, and rewrites with local llama.cpp by default or the
  user's ChatGPT account. It is closed source, so only the UX was adopted. Reuse: the modes, local-first defaults, and the "use your own sign-in" model.
- **OpenWhispr** is already a documented client of this app's STT server (STT.md). It shows the hold-to-dictate pattern the owner uses.
- **Grammarly and Wispr Flow** are UX references only. Real in-app underlines (Grammarly) need per-app overlays and were rejected as too large.
- **Limits:** no source code for Snapdraft. No external skill or library search was run (see Skill handoff).

### UX review (second Claude Opus, read-only)

It confirmed the bar is overloaded and recommended an intent-based bar with an overflow menu. It flagged risks: undo, a context change
during generation, clipboard restore, latency feedback, apps that block paste, and editable-field detection failing in web views and
Electron apps. Its two code claims (dimmed buttons, click-away only when idle) were verified above.

