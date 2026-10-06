<img src="assets/icon.svg" width="64" height="64" alt="">

# select-to-tts

Select text in any Windows app and a small **▶ Auto ▾** button appears next to it. Press ▶ to hear the text read aloud. Press ■ to stop.

Voices come from your existing **Codex / ChatGPT subscription** (Codex realtime voice, no OpenAI API key). If Codex is unavailable, the app falls back to Edge neural voices, then to the offline Windows voices.

## Requirements

- Windows 11, Python 3.11, [uv](https://docs.astral.sh/uv/)
- [Codex CLI](https://github.com/openai/codex) installed with npm and signed in with ChatGPT (`codex login`)

## Run

```powershell
uv sync
uv run select-to-tts            # or start .venv\Scripts\select-to-tts.exe (no console window)
```

A tray icon appears. Its menu has these options:

- **Auto (Codex, then Edge, then Windows)**: the default.
- **Codex only**, **Edge only**, or **Windows only (offline)**: "only" really means only. Windows only never sends text off the machine.
- **Clipboard fallback**: lets the app borrow Ctrl+C for apps that hide their selection from UI Automation, such as VS Code. Every clipboard format is restored afterwards.
- **Last engine**: shows which engine spoke most recently.
- **Quit**

To start the app at login, put a shortcut to `.venv\Scripts\select-to-tts.exe` in `shell:startup`.

## How it works

| Piece | File |
| --- | --- |
| Mouse hook. A drag or double-click means text may be selected | `trigger.py` |
| Selected text via UI Automation, else a borrowed Ctrl+C with full clipboard restore. Password fields are never read | `selection.py`, `clipboard.py` |
| Floating button that never steals focus, with the language menu | `popup.py` |
| Codex realtime over `codex app-server`, using WebRTC v3 (the only transport that works without an API key) | `codex_rt.py` |
| Edge and Windows fallbacks, plus the ordered chain | `engines.py` |
| Tray icon and wiring | `__main__.py` |

Details, evidence, and the T1 feasibility results are in [PLAN.md](PLAN.md).

## Test

```powershell
uv run python -m unittest discover -s tests
uv run python -m select_to_tts.codex_rt "שלום עולם" he-IL     # hear the Codex engine directly
```

## Known limitations

- Codex's realtime API is marked experimental. A Codex update can break it, and the app then falls back to Edge.
- Roughly 1 in 12 Codex reads in testing ended early or stayed silent. Silence falls back automatically. An early stop does not.
- Each popup shown pre-starts a short Codex voice session so ▶ answers in about 1 s.
- Choosing a language from the menu moves keyboard focus away from the source app. The text is already captured.
- Only mouse selections trigger the button. Keyboard selections (Shift+arrows) don't.
