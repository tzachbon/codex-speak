# Contributing

Thanks for helping. Bug reports, fixes, docs, and new language voices are all welcome.

## Before you start

- For anything larger than a small fix, open an issue first so we can agree on the approach.
- Keep pull requests focused on one change. Small, readable diffs get merged faster.
- By contributing, you agree that your work is released under the [MIT license](LICENSE) and that you follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up

You need Windows 11. The app uses Windows-only APIs (UI Automation, COM, the mouse hook), so it does not run on macOS or Linux.

1. Install [uv](https://docs.astral.sh/uv/). It installs the Python version from `.python-version`.
2. Clone the repo and run:

```powershell
uv sync
uv run codex-speak
```

The Codex CLI is optional. Without `codex login`, the app uses the Edge and Windows voices, which is enough for most work.

## Test

```powershell
uv run python -m unittest discover -s tests
```

CI runs the same command on `windows-latest` for every pull request. Add or update a test for the behavior you change. Tests that need a network or a Codex login must be opt-in, like the live speech-to-text check below.

Some checks are manual:

```powershell
uv run python -m codex_speak.codex_rt "Hello world" en-US    # hear the Codex engine directly
```

The live speech-to-text check needs a Codex login and uses subscription quota. It only runs when `STT_LIVE_CHECK=1` is set. See [STT.md](STT.md).

## Build the installer

Requires PowerShell 7.4+ (`pwsh`) and [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```powershell
.\packaging\build.ps1           # PyInstaller app folder, then dist\CodexSpeak-Setup.exe
```

## Code map

| Piece | File |
| --- | --- |
| Mouse hook. A drag or double-click means text may be selected | `trigger.py` |
| Selected text via UI Automation, else a borrowed Ctrl+C with full clipboard restore. Password fields are never read | `selection.py`, `clipboard.py` |
| Floating bar that never takes focus, with the language and speed menus | `popup.py` |
| Sentence units and the caption line | `sentences.py`, `captions.py` |
| Settings window and stored settings | `settings_ui.py`, `settings.py` |
| Codex realtime over `codex app-server`, using WebRTC v3 (the only transport that works without an API key) | `codex_rt.py` |
| Edge and Windows fallbacks, plus the ordered chain | `engines.py`, `edge_stream.py` |
| Speaker output and the slow-down time stretch (ffmpeg `atempo`) | `audio.py` |
| Update checks and installs | `updates.py` |
| Speech-to-text adapter and local HTTP server | `stt.py`, `stt_server.py` |
| Tray icon and wiring | `__main__.py` |

Other files:

- [PLAN.md](PLAN.md): the design history, with the evidence behind each decision.
- [STT.md](STT.md): the speech-to-text server and its HTTP contract.
- `spikes/`: throwaway feasibility probes and their results. Not shipped.
- `packaging/`: PyInstaller launcher, Inno Setup script, and the build script.
- `docs/`: the GitHub Pages site and the screenshots used in the README.

## Privacy rules

These protect users. Please keep them:

- Never log selected text, transcripts, audio, or URLs with access tokens.
- Never read password fields.
- Never send text off the PC when the user picked "Windows only".
- Restore the clipboard exactly after borrowing Ctrl+C.

## Releases

CI (`.github/workflows/build.yml`) tests and builds pull requests. Every successful push to `master`, including a merged PR, automatically publishes a release with the installer attached.

Versions follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `feat:` adds a minor version, a `!` header or `BREAKING CHANGE:` footer adds a major version, and everything else adds a patch. Scoped headers such as `feat(captions):` work too. Each commit on master's first-parent history advances the version once, so delayed builds cannot claim the same version for different commits. A normal merge includes its new branch commits when choosing the bump. A rebase merge can skip unused version numbers.

The release tag is the published version. CI stamps that version into `pyproject.toml`, the lockfile, the bundled app metadata used by update checks, and the installer in its build checkout. Source archives and source checkouts retain the development version. Manual stable `vMAJOR.MINOR.PATCH` tag pushes still build and publish that exact version. Releases wait for tests and the installer build, and delayed older releases do not replace a newer release as Latest.

Rerunning a failed release reuses its tag and completes an unfinished draft without replacing uploaded assets. An empty or incomplete installer asset fails closed and needs recovery before rerunning.
