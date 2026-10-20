## Requirements and constraints

| ID | Requirement |
| --- | --- |
| R1 | Rewrite a selection in place from the bar on Mac and Windows, with no panel. |
| R2 | Toast after every in-place change, with Undo, Review, and Mode. It auto-hides after about 6 s and pauses on hover. |
| R3 | Review opens panel B: original on the left, rewrite on the right with word-level marks, per-change undo, Rewrite again, Copy, Replace. |
| R4 | Rewrite shortcut: a single press uses the default mode, a double press (within 350 ms) opens the mode menu, and with no selection it shows a hint only. |
| R5 | Hold-to-dictate shortcut: record, transcribe, rewrite with the default mode, type at the caret, then the toast. |
| R6 | LLM sources Cursor → Codex → Local, each toggleable and orderable, with model and effort menus where supported. Fallback on failure. |
| R7 | STT sources Codex → Cursor (if its spike passes). No local STT in this plan. |
| R8 | Built-in modes Fix errors, Message, Email, Improve writing. User-defined modes have a name and instructions. One default mode. |
| R9 | Bar layouts as specified in the Technical section. Close is removed, Esc dismisses, and "…" holds the rest. |
| R10 | Never paste if the frontmost app or window changed, or if the current selection no longer equals the original. Offer Copy instead. |
| R11 | Never read or replace secure or password fields. The log never contains text, prompts, or transcripts. |
| R12 | Restore the clipboard after a paste unless it changed in between (Windows `sequence()`, Mac `changeCount`). |
| R13 | Cursor LLM and STT ship only if spike S1 passes. Otherwise they are hidden and the plan continues with Codex and Local. |

Constraints: no new paid APIs or API keys. Keep the existing module style (short modules, docstrings that explain constraints, no comments restating code).
Keep `unittest`, not pytest. Do not stream partial text into the target field.

## Decisions and assumptions

- Decision (owner): sources follow the voice order, Cursor → Codex → Local, with model and effort selection.
- Decision (owner): the hotkey flow works on existing text in place. The panel is optional. Both platforms.
- Decision (owner): dictation output is always rewritten.
- Decision (owner delegated, "I'm trusting you"): intent-based bar with a "…" menu. Review uses panel B. With no selection, the hotkey shows a hint only.
- Decision: in-place replacement uses the clipboard (set text, send Cmd+V or Ctrl+V, restore). There is no portable AX or UIA setter that keeps app undo.
- Decision: writer settings are separate keys (`writer_sources`, `writer_models`, `modes`, ...). The default order is copied from the voice order once.
- Assumption: the Codex `turn/start` notifications for the final agent message match the schema at execution time. Validate in T2 with the generated schema.
- Assumption: Cursor's chat and transcription RPCs can be called like TextToSpeech. Validate in S1. R13 covers failure.

## Scope

### In scope
Writer core (modes, prompts, source chain, model and effort lists), Codex text turns, generalized local Qwen completion, Cursor spike and
adapter, in-place replace with undo and guards, bar redesign (Mac and Windows), toast, Review panel B, rewrite and dictation hotkeys,
microphone capture and permission, Settings → Writing and Dictation, README, tests, and Windows validation on Tzach-PC.

### Out of scope
In-app underlines, a standalone compose overlay with draft history, local STT (whisper.cpp), keeping rich-text formatting on paste
(plain text only in v1), streaming output into the field, and Linux.

## Impact and blast radius

- **Benefit:** one keystroke or one bar click turns a draft or dictation into a polished message where the owner is already typing.
- **Affected code:** `core.py` (new events), both `popup.py` files (layout rewrite), both `trigger.py` files (hold hotkey), `settings.py`
  defaults and migration, both Settings UIs, `summarize.py` (generalized completion), `codex_rt.AppServer` (reused for text turns),
  and packaging (Mac mic permission).
- **Indirect:** the bar change affects every existing reading user. Read, Summarize, skip, and source-switching behavior must stay
  reachable. `tests/test_mac_popup.py`, `tests/test_popup_settings.py`, and the Windows popup tests will need updates.
- **Data flow change:** selected or dictated text goes to Cursor or OpenAI when those sources are on. That is already true for reading. Local stays on device.
- **Unknown:** how each target app handles a synthetic paste and its undo stack. This is covered by the manual matrix in T9.

## Reversibility and recovery

- All code changes are **two-way doors**. They ship behind a Settings toggle *Writer* (default on after T9 passes) and revert per PR.
- The settings schema gains keys only. Older builds ignore unknown keys, so a downgrade is safe.
- **One-way door:** the Mac microphone permission prompt. Once granted or denied, it persists in TCC. Recovery is
  `tccutil reset Microphone <bundle id>` or System Settings. Mitigation: prompt only on first dictation, not at launch.
- **One-way door per use:** a paste into a third-party app is an external side effect. Toast Undo re-pastes the original only while the inserted text still matches.
  Otherwise the app's own Cmd+Z or Ctrl+Z is the only recovery.

## Approach

Build a shared **writer core** (pure Python, testable) that turns `(text, mode)` into a rewrite through an ordered **source chain**.
Each source is an adapter with `status()`, `models()`, and `rewrite(text, instructions, model, effort, cancelled)`. Platform code supplies three
capabilities: **read the selection plus context**, **replace in place**, and **record audio**. `core.App` gains a `Writer` mixin,
like `Summaries`, that coordinates events, the toast, undo, and the panel.

Sequence: the spike first, because it decides R13. Then the core and sources (no UI). Then replace, which is the riskiest platform work. Then the bar,
toast, and panel. Then hotkeys and dictation. Then Settings, docs, and Windows validation.

Alternatives rejected:
- **Always open a panel** (Snapdraft style): rejected by the owner, because it is slower for the main flow.
- **AX `AXSelectedText` set or UIA `ValuePattern.SetValue`:** works in some native fields but breaks the app's undo and fails in Electron and web apps.
  Kept only as a possible future fallback.
- **Separate writing source list order from scratch:** rejected. It copies the voice order as its default to match the owner's mental model.

