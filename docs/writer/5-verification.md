## Cross-cutting concerns

- **Privacy:** the log records only source names, timings, and error type names. Never text, prompts, transcripts, or model replies (existing invariant, for example the `log.info` call in `app_summarize.py` line 100 that logs only the error type).
- **Threads:** all model, STT, and recording work runs on workers. UI changes go through `self.events` on the main thread, matching existing code.
- **Accessibility permission (Mac):** synthetic Cmd+V needs the same Accessibility trust the app already requests.
- **Updates:** Mac `LSUIElement` and signing are unchanged apart from the new microphone keys. Re-test the in-app updater after packaging changes.

## Acceptance criteria

| Requirement | Acceptance condition | Tasks | Evidence |
| --- | --- | --- | --- |
| R1, R12 | Replace works in 3 apps per platform, clipboard intact | T4, T6, T9 | matrix screenshots, `test_edit_logic` |
| R2 | Toast shows, Undo restores, auto-hides | T5, T6 | manual matrix |
| R3 | Panel B shows the diff, per-change undo, Replace guarded | T5 | manual + `test_writer.diff` |
| R4 | Single, double, and no-selection behavior | T6 | manual |
| R5, R7 | Hold, speak, release types rewritten text | T7 | manual on signed Mac build and Tzach-PC |
| R6 | Order, toggles, model and effort, fallback | T1–T3, T8 | `test_writer`, `test_llm_codex`, manual |
| R8 | Built-in and custom modes work | T1, T8 | tests + manual |
| R9 | Three bar layouts, "…" routes correctly, Esc dismisses | T5 | popup tests + manual |
| R10, R11 | No paste on changed context, secure fields skipped, log clean | T4, T6 | `test_edit_logic`, `assertLogs` tests, manual with a password field |
| R13 | Cursor visible only if S1 passed | S1, T3 | S1 notes |

## End-to-end verification

On each platform: (1) type "hey i think we should of shipped it lol" in Slack, select it, pick ✎ → Message, and confirm the text is replaced and the clipboard still holds
a sentinel string copied beforehand. (2) Press Undo and confirm the original is back. (3) Select again, press the rewrite shortcut twice, pick Email, then Review, then revert one change, then Replace.
(4) Click into an empty Notepad or TextEdit line, hold the dictation shortcut, say a sentence, release, and confirm a rewritten sentence appears. (5) Turn off Cursor and Codex
in Settings → Writing, repeat step 1, and confirm the toast names Local. (6) Start a rewrite, switch apps before it finishes, and confirm no paste happens and the toast offers Copy.
(7) Read any text aloud and confirm play, skip, speed, and voice still work from the new bar and "…". Failures block the T9 default switch.

## What can go wrong

| Failure scenario | Consequence | Detection | Prevention / task | Stop and recovery | Residual |
| --- | --- | --- | --- | --- | --- |
| Cursor RPC shape unknown or changes | Cursor writer or STT fails | S1 probes, runtime `Error` | spike gate, chain fallback (S1, T1) | hide Cursor (R13) | an update can break it, like TTS today |
| Paste lands in the wrong app | Text inserted somewhere else | `same_context` false | guard before paste (T4, T6) | toast offers Copy | a race window of about 150 ms |
| App blocks synthetic paste | Nothing replaced | selection unchanged after `replace` | verify after paste (T4) | open panel B with Copy | some apps need manual paste |
| Clipboard lost | User loses copied data | `changeCount`/`sequence` mismatch | snapshot all formats, conditional restore (T4) | skip restore if changed | clipboard managers may log the temporary text |
| Undo corrupts text | Wrong text replaced | text check fails | only undo while inserted text still matches (T6) | point to app undo | none beyond app undo |
| Mic permission denied | Dictation silent | AVCapture status | prompt on first use, Settings shows status (T7, T8) | button opens System Settings | none |
| Bar regression for readers | Reading flow harder | popup tests, manual step 7 | keep every action reachable from "…" (T5) | revert PR2 | users relearn the layout |
| Local model too slow or too long input | Long wait | spinner time | MAX_CHARS, cancel with Esc (T1, T6) | fall through to next source | 8 GB Macs are slow |
| Esc passes through to the app on Mac | Slack may close a thread or clear a draft | manual matrix | Esc watcher only while the bar or a rewrite is shown (T5) | cancel still works, app side effect stays | accepted on Mac |
| Prompt injection in selected text | Model follows text instructions | output review | system prompt rule, output schema (T1, T2) | Undo | a small model may still comply |

## Open and deferred items

- Local STT (whisper.cpp) → owner → after v1 → dictation needs Codex or Cursor until then.
- Rich-text paste (keep bold and links) → owner → after v1 → plain text only.
- Starting the Tzach-PC thread → owner, in the T3 app → before the Windows halves of T4, T5, T7, T8 → no Windows evidence without it.
- Exact default shortcut letters (E and D) → executor checks for conflicts with common apps during T6 → change in Settings if needed.

## Skill handoff

- Skill discovery: `INCOMPLETE`. Installed skills were reviewed, but no external skill search was run for desktop UI automation, macOS AX, or Windows UIA.
- During planning: `grill-me` style question waves (4 rounds with the owner). A second Claude Opus did a read-only UX review. Mockups were made as HTML.
- During execution:
  - T1–T8 → `tdd` → when adding each pure-logic module → failing test first, then the code.
  - Per PR → `create-pr` → after each stack layer → a PR on top of the previous layer, linked to this thread.
  - CI failure → `fix-ci` → on a red `windows-latest` or `macos-latest` job → a scoped fix.
  - Before merge → `review-pro-max` → on each PR → merge blockers.
- External candidates and installation: none selected.

## References

- Repo files cited above, branch `feat/add-snapdraft-harness-discussion` at `56ac1bc`.
- Snapdraft README: https://github.com/ranyitz/snapdraft
- Codex app-server schema: `codex app-server generate-json-schema` (codex-cli 0.163.0), `v2/TurnStartParams.json`, `v2/ModelListResponse.json`.
- Mockups: `docs/writer/writer-mockups.png`, `docs/writer/inplace-mockups.png`, `docs/writer/bar-declutter.png`.
