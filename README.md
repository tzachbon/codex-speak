<div align="center">

<img src="docs/icon.png" width="80" height="80" alt="">

# Codex Speak

**Select text in any Windows app and hear it in your ChatGPT voice, through Codex.**

Codex Speak runs the Codex realtime voice from your ChatGPT sign-in through `codex app-server`. No OpenAI API key. Edge neural voices and offline Windows voices take over when Codex can't speak.

<sub>Unofficial. Not affiliated with OpenAI.</sub>

[![Build](https://github.com/tzachbon/codex-speak/actions/workflows/build.yml/badge.svg)](https://github.com/tzachbon/codex-speak/actions/workflows/build.yml)
[![Latest release](https://img.shields.io/github/v/release/tzachbon/codex-speak)](https://github.com/tzachbon/codex-speak/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
![Windows 11](https://img.shields.io/badge/Windows-11-0078d4)

[**Download for Windows**](https://github.com/tzachbon/codex-speak/releases/latest/download/CodexSpeak-Setup.exe) · [Website](https://tzachbon.github.io/codex-speak/) · [Report a bug](https://github.com/tzachbon/codex-speak/issues/new/choose)

![The playback bar above selected text](docs/popup.png)

</div>

## What it does

- **Works in most apps.** Drag or double-click to select text in a browser, Notepad, VS Code, or most other apps. A small **▶ Auto ⌄ 1× ⌄** bar appears next to the selection without taking focus.
- **Reads with your ChatGPT voice.** Codex realtime voice through the [Codex CLI](https://github.com/openai/codex) sign-in. It uses your plan's Codex access and counts toward its limits.
- **Always has a voice.** If Codex can't speak, Edge neural voices take over, then the offline Windows voices.
- **Pause, resume, stop.** ⏸ pauses and ▶ continues from the same spot. ■ stops.
- **Speed on the bar.** 0.5× to 2×, saved and shared with Settings.
- **Read-along captions.** The current sentence appears above the bar as it plays.
- **Six languages.** Hebrew, English, Arabic, Russian, Spanish, and French.
- **Updates itself if you want.** Optional automatic updates from GitHub releases, verified by SHA-256.
- **Speech-to-text server (optional).** An OpenAI-compatible local endpoint that transcribes with the same Codex sign-in. See [STT.md](STT.md).

![Read-along caption above the playback controls](docs/captions.png)

## Install

1. Download **[CodexSpeak-Setup.exe](https://github.com/tzachbon/codex-speak/releases/latest/download/CodexSpeak-Setup.exe)** and run it. It installs for your user only and needs no admin rights.
2. The installer isn't code-signed, so SmartScreen may warn you. Choose *More info*, then *Run anyway*.
3. Optional, for the ChatGPT voice: install the [Codex CLI](https://github.com/openai/codex) (`npm i -g @openai/codex`) and sign in once with `codex login`. Without it, the app uses the Edge and Windows voices.

Requirements: Windows 11, 64-bit.

**Upgrading from Select to TTS?** This is the same app under a new name. Run the new installer. It replaces Select to TTS, and your settings, sign-in startup choice, and speech-to-text URL carry over.

## Use

1. Select text with the mouse (drag or double-click).
2. Press ▶ on the bar. The language menu defaults to Auto.
3. Pick a speed from the bar's speed menu.
4. ⏸ pauses and ▶ continues. ■ stops. Selecting new text while paused replaces the paused read.

Click ⚙ on the bar, the tray icon, or start the app again from the Start menu to open **Settings**.

## Where your text goes

| Voice | Needs | Speed | Where your text goes |
| --- | --- | --- | --- |
| Codex realtime | Codex CLI signed in with ChatGPT | 0.5× to 1×. Above 1×, Auto starts with Edge | OpenAI, through your Codex sign-in |
| Edge neural | Internet | 0.5× to 2× | Microsoft's Edge read-aloud service |
| Windows | Nothing, it's built in | 0.5× to 2× | Stays on your PC |

- Choose **Windows only** in Settings to keep text on your PC.
- Password fields are never read.
- The Ctrl+C fallback is skipped in terminal windows, where it would interrupt a running command.
- The log records the engine, timing, and errors, never the text itself.
- In Auto, Codex works out the language itself. Edge and Windows pick Hebrew, Arabic, or Russian voices from the script and use English for everything else. Choose Spanish or French from the menu for those voices.

## Settings

<img src="docs/settings.png" width="260" align="right" alt="The Settings window: sign-in startup, updates, speed, voice, captions, selection, and speech-to-text">

- **Start when I sign in to Windows**: adds or removes a Task Scheduler logon task named "Codex Speak".
- **Check and install update / Install updates automatically**: see [Updates](#updates).
- **Speed**: 0.5× to 2×. Changes apply to the next read.
- **Voice**: Auto (Codex, then Edge, then Windows), or one engine only.
- **Captions**: font size (8 to 24 points), optional background, and background opacity. Changes apply to the visible caption right away.
- **Read apps that hide their selection**: for apps such as VS Code, the app borrows Ctrl+C and then restores every clipboard format.
- **Prepare speech as soon as I select text**: off by default. When Edge reads, the app requests the first sentence's audio as soon as the bar appears. This sends that sentence to Microsoft before you press play.
- **Speech-to-text server**: see [STT.md](STT.md).

Settings are saved in `%APPDATA%\codex-speak\settings.json`, next to a small `codex-speak.log`.

<br clear="right">

<details>
<summary><b>Speed details</b></summary>

Edge and Windows voices support the full range. Codex streams speech in real time, so it can only be slowed down. Above 1×, Auto starts with Edge, and "Codex only" reads at its natural pace.

</details>

<details id="updates">
<summary><b>Updates</b></summary>

**Check and install update** checks the latest stable GitHub release, verifies the installer's size and SHA-256 digest, installs it into the current app folder, and relaunches. It waits for speech, including paused speech, and active transcriptions to finish.

**Install updates automatically** is off by default. When on, the app checks shortly after startup and every 24 hours, and installs when idle. Turning it off cancels a pending automatic installation. Settings and your sign-in startup choice are kept.

If a check or download fails, the app keeps running and Settings shows the error. Downloaded installers and `setup.log` are kept under `%LOCALAPPDATA%\codex-speak\updates` for diagnosis and removed on uninstall. The digest checks that the download matches GitHub's release metadata. The installer is unsigned, so the updater trusts this repository's release account.

Update controls are disabled when running from source.

</details>

<details>
<summary><b>Uninstall</b></summary>

Use *Settings > Apps > Codex Speak*. This removes the app, its sign-in task, and its caches in `%TEMP%`. Your settings and log in `%APPDATA%\codex-speak` are kept.

</details>

## Known limitations

- Codex's realtime API is marked experimental. A Codex update can break it, and the app then falls back to Edge.
- Speech is submitted one sentence or paragraph at a time, so gaps and changes in prosody can occur. Abbreviations can create shorter units. After the first successful sentence, the same engine reads the rest. Voice, language, and speed changes apply to the next complete selection.
- Roughly 1 in 12 Codex reads in testing ended early or stayed silent. Silence falls back automatically. An early stop does not.
- Each popup shown pre-starts a short Codex voice session. Sentence handoffs may need another session.
- Choosing a language from the menu moves keyboard focus away from the source app. The text is already captured.
- Only mouse selections trigger the bar. Keyboard selections (Shift+arrows) don't.
- Pausing the Windows voice takes effect after about a second, because SAPI keeps playing audio it has already buffered. Codex and Edge pause at once.

## Run from source

```powershell
uv sync
uv run codex-speak            # or start .venv\Scripts\codex-speak.exe (no console window)
uv run python -m unittest discover -s tests
```

[CONTRIBUTING.md](CONTRIBUTING.md) covers the dev setup, building the installer, releases, and a map of the code.

## Contributing

Bug reports, fixes, and new language voices are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Not affiliated with OpenAI or Microsoft.
