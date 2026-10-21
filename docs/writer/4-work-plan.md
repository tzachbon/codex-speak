## Work plan

Suggested PR stack, each on top of the previous one: PR1 = S1 + T1 + T2, PR2 = T3 + T4, PR3 = T5 + T6, PR4 = T7, PR5 = T8 + T9.

### S1. Cursor RPC spike (time-boxed to 1 working day)

**Result (2026-10-21, Mac): passed, with a change of transport for chat.** Probes are in `spikes/`.
- `AiService/TranscribeAudio` (desktop sign-in, unary protobuf: 1 `audio` bytes, 2 `mime_type`, 3 `language` optional, reply 1 `text`) returned an exact transcript.
- `AiService/AvailableModels` listed 24 models with a `supports_thinking` flag.
- `AiService/StreamChat` and `ChatService/StreamUnifiedChat` reply `ERROR_DEPRECATED`. Not usable.
- `cursor-agent -p` works but takes 33 to 43 s per call. Too slow.
- A warm `cursor-agent acp` process (Agent Client Protocol, JSON-RPC over stdio) rewrites in 1.8 to 3.5 s after a 4 s start. `session/new` returns
  `models.availableModels` with bracket parameters for effort (for example `claude-opus-5-5[context=300k,effort=medium,fast=false]`) and `modes` agent, plan, ask.
- Codex for comparison (`spikes/codex_text_probe.py`): 0.7 s start, 5.7 s turn, 7 visible models with their effort lists.

**Decision:** `CursorWriter` drives a warm `cursor-agent acp` process in `ask` mode, refuses every permission request, and uses an empty temp `cwd`.
`CursorStt` uses `TranscribeAudio` with the desktop sign-in. The Cursor writer needs the Cursor CLI installed and signed in (`cursor-agent status`),
so Settings shows Install and Sign in fixes for it like the other sources.

**Purpose:** decide R13. **Starting context:** `cursor_tts.py` shows how to encode, call, and decode. Field numbers come from the Cursor bundle
`/Applications/Cursor.app/Contents/Resources/app/out/vs/workbench/workbench.desktop.main.js` (search `AvailableModels`, `StreamChat`,
`TranscribeAudio`, then the generated `fields` arrays next to each message class).

- [ ] Write `spikes/cursor_chat_probe.py`. List models (`AvailableModels` or `GetUsableModels`), then send one short rewrite through the simplest
      chat RPC (prefer a unary or server-stream call over `StreamUnifiedChatWithTools`). Print only the status, model ids, and reply length.
- [ ] Write `spikes/cursor_stt_probe.py`. Send a 3 s WAV to `TranscribeAudio` and print the transcript length.
- [ ] Record the request and response field maps, and whether effort or thinking-level exists (the bundle has `thinkingLevel`), in `spikes/README` or a docstring.

**Completion gate:** both probes return a non-empty result 3 times in a row with the owner's sign-in. **Failure:** if either fails after one day,
mark that Cursor capability hidden (R13), note it in the plan's open items, and continue. **Handoff:** field maps feed T3.

### T1. Writer core

- [ ] Create `writer.py` with `Mode`, `BUILTIN_MODES`, `system_prompt`, `rewrite` (chain), `diff`, and the errors, as specified above.
- [ ] Built-in instructions. Fix errors: "Fix spelling, grammar, and punctuation only. Keep wording and tone." Message: "A short, friendly chat
      message." Email: "A clear email with greeting and sign-off." Improve writing: "Clearer and more concise, same tone."
- [ ] Add the settings defaults. `settings.load` already fills missing keys from DEFAULTS (around line 57), so the first-run copy must happen
      before that fill. When `"writer_sources" not in saved`, derive its order from the saved `sources` (Cursor and Codex relative order, Local last).
      Follow the same pattern as the legacy check around line 69. Add a test for both a fresh file and an existing file.
- [ ] Tests in `tests/test_writer.py`: the chain skips disabled and not-ready sources, falls back on `Error`, stops on `Cancelled`, and never puts text in the log
      (use `assertLogs` and check that the text is absent). Check `diff` on insert, delete, and replace. Check that a custom mode overrides by name.

**Gate:** tests pass locally on Mac.

### T2. Codex and Local adapters

- [ ] Run `codex app-server generate-json-schema --out <tmp>` and confirm the turn-completion notification and agent-message item shapes. Write the adapter against them.
- [ ] Implement `llm_codex.CodexWriter` (models cached 10 minutes, `turn/interrupt` on cancel, 60 s timeout, reuse one `AppServer` per rewrite and close it after).
- [ ] Extract `summarize.Server.complete(system, user, max_tokens=800)`. `summarize()` calls it with PROMPT, so Summarize behavior stays the same.
      Add `LocalWriter(server)`, constructed with `App.summary_server`, and reset the idle stop the same way `_summary_done` does.
- [ ] Tests with a fake `AppServer` (`call` recorder) check the exact `turn/start` params, including `model` and `effort`, and the JSON `.text` extraction.
      The existing `tests/test_summarize.py` still passes.

**Gate:** a manual run on Mac rewrites one sentence through Codex with two different efforts, and through Local.

### T3. Cursor adapter (only if S1 passed)

- [ ] `llm_cursor.CursorWriter`: one warm `cursor-agent acp` process started on first use and stopped after 300 s idle. A new session per rewrite, in `ask` mode,
      `session/set_model` from the saved model id. It refuses every client request and collects `agent_message_chunk` text. Status comes from `cursor-agent status`.
- [ ] `llm_cursor.CursorStt`: `TranscribeAudio` with the same `_NoRedirect` opener and error policy as `cursor_tts`.
- [ ] Unit tests on encode and decode with recorded byte fixtures (no network).

**Gate:** a manual rewrite and transcript through Cursor. **Failure:** keep the module out of the chain (R13).

### T4. In-place edit capability (Mac and Windows)

- [ ] Mac `mac/edit.py`: `capture` uses AX (`_via_ax`) for the text, editable role, and `AXSubrole == AXSecureTextField`, plus `secure_input()`.
      The context is `(pid, window number)`. `replace` uses `pasteboard.snapshot`, puts plain text, sends Cmd+V through `CGEventPost`, sleeps 150 ms,
      and restores if `changeCount` equals the value it set.
- [ ] Windows `win/edit.py`: `capture` uses UIA, editable through ValuePattern or TextPattern, `IsPassword`, the hwnd, and process id. `replace` uses
      `clipboard.snapshot`, sets `CF_UNICODETEXT`, sends Ctrl+V through `SendInput`, waits 150 ms, and restores if `sequence()` equals the value after the set.
      It refuses terminal window classes, like `_foreground_class`.
- [ ] Implement `select_back(n)` on both platforms (AX `AXSelectedTextRange` or UIA `TextRange.Select`, with Shift+Left × n as the fallback).
- [ ] Pure-logic tests (`tests/test_edit_logic.py`): restore is skipped when the clipboard changed. `same_context` is false on an app, window, or text change,
      and false when the fallback read returns empty. The undo sequence calls `select_back`, then the check, then `replace`, and stops if the check fails.
      The length helper gives the right UTF-16 count for an emoji case and a multi-line case.
- [ ] **Windows half runs on Tzach-PC** in a T3 thread on that environment, on the same branch. Use the brief in "Windows execution brief" below.

**Gate:** a manual replace in the 3 apps per platform from the Definition of Done, with the clipboard content identical before and after (copy a known string first).
**Failure:** if an app swallows the paste, `replace` returns False after verifying the selection text did not change. The Writer then opens panel B with Copy.

### T5. Bar redesign, toast, Review panel B

- [ ] Rework both `popup.py` files into three layouts plus the "…" menu (table above). Remove Close and the dimmed transport buttons.
- [ ] Add the temporary Esc watcher described in the low-level notes. Mac uses an `NSEventMaskKeyDown` monitor for key code 53, and Windows uses a pynput listener. It is active only while something is shown.
- [ ] Add `set_mode(editable)` called from `core` on `"show"` with `edit.capture(clipboard_fallback=False).editable`.
- [ ] Add `toast.py` per platform: the same HUD pill style (Mac `NSVisualEffectMaterialHUDWindow`, radius 21), non-activating, about 6 s auto-hide, paused on hover.
- [ ] Add `review.py` per platform for panel B.
- [ ] Update popup tests for the new control sets, and add tests for "…" menu routing (Voice, Language, Speed, Summarize, Settings still call the same callbacks).

**Gate:** reading, summarize, skip, and source switching still work from the new bar (manual on both platforms). Tests pass.

### T6. Rewrite hotkey and Writer mixin

- [ ] Add `app_writer.Writer` (mixin on `core.App`): `rewrite_selection(mode)`, `_rewrite_done`, `undo_last`, `open_review`, and the `rid` and cancel handling, like `Summaries`.
- [ ] Register `rewrite_hotkey` (single press is the default mode, a second press within 350 ms shows the mode menu at the pointer). With no selection, the toast says "Select text to rewrite".
- [ ] Show a spinner on ✎ or in the toast with the source name while it works. Esc cancels.
- [ ] Add a shortcut conflict check in `hotkeys.py` across `hotkey`, `rewrite_hotkey`, and `dictate_hotkey`.

**Gate:** Definition of Done items 1 to 3 pass manually on Mac, including toast Undo restoring the original in all 3 apps. Windows is verified in T9.

### T7. Dictation

- [ ] Add `mic.py` (sounddevice InputStream, a 60 s cap that matches `stt.MAX_SECONDS`, WAV encode with the `wave` module).
- [ ] Add hold support to both `trigger.HotKey` classes. On down: check the mic permission, start recording, show the pill "Listening · Codex". On up: stop, then
      transcribe through the STT chain (`stt.transcribe`, then `CursorStt`), then `writer.rewrite` with the default mode, then `edit.type_at_caret`, then the toast.
- [ ] Add the Mac packaging changes for the microphone.
- [ ] Tests: the tap-to-cancel threshold, the STT chain fallback order, and that WAV headers match what `stt.decode_audio` accepts.

**Gate:** Definition of Done item 4 on Mac from a signed local build (`packaging/build_mac.sh`), so the permission prompt is real.

### T8. Settings → Writing and Dictation

- [ ] Add a Writing page per platform: sources list (toggle, ↑ ↓, status, Sign in/Download fixes reusing `sources.fix`), model and effort menus populated
      from `models()` (Local shows "Qwen3-4B", fixed), default mode, modes editor (add, rename, edit instructions, delete custom), and the rewrite shortcut row
      (reuse `shortcut_row.py` on Windows and the Reading page pattern on Mac).
- [ ] Add a Dictation section: STT sources, the hold shortcut, and the microphone status.
- [ ] Add settings round-trip tests.

### T9. Docs and cross-platform validation

- [ ] README: add Writer and Dictation bullets under "What it does", add Writer rows to "Where your text goes", and add the new Settings entries.
- [ ] Run the manual matrix on Mac and on Tzach-PC (the Windows thread). Retain screenshots in the PR. Items: DoD 1 to 7 × the 3 apps per platform.
- [ ] Turn the default of `"writer"` on only after the matrix passes.

## Windows execution brief (for the Tzach-PC T3 thread)

Start a T3 thread on the `Tzach-PC` environment in its harness-discussion checkout, on the branch of the PR being validated. Message:
"Pull branch `<branch>`. Run `uv sync` and `uv run python -m unittest discover -s tests`. Implement or fix the Windows half of task `<T4|T5|T7|T8>` from this plan
(paste the task section). Then run `uv run harness-discussion` and walk through the manual checks listed in that task's gate in Notepad, Slack, and Edge.
Report each check as pass or fail with a screenshot path. Commit to the same branch. Do not push without the owner's approval."

