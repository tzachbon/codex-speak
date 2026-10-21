# Writer: Mac and Windows agent sync

Two agents build `docs/writer/PLAN.md` on branch `feat/add-snapdraft-harness-discussion`.
Zach approves every push. Pull before reading, append below, then commit and ask Zach to push.

## Ownership

| Agent | Owns |
| --- | --- |
| Mac | S1 spike, shared modules (`writer.py`, `llm_*.py`, `mic.py`, `app_writer.py`, `settings.py`, `hotkeys.py`), all of `mac/` |
| Windows | everything under `win/`, Windows checks in each task gate, the T9 Windows matrix |

Shared files changed by the other side: propose the change here first instead of editing.

## Log

Newest entry last. Format: `### <date> <Mac|Windows>`, then status, blockers, and questions for the other agent or Zach.

Earlier entries, oldest first: [SYNC-log-1.md](SYNC-log-1.md), [SYNC-log-2.md](SYNC-log-2.md), [SYNC-log-3.md](SYNC-log-3.md). Keep this file under 20 KB (the pre-commit size limit). Move older entries to a new part when it grows.

### 2026-10-21 Mac (T5 to T9 Mac, contract answers)

- Pulled `8b6df99` and rebased onto it. Windows entries read. Local Mac commits on top: `92461e6` (T2), `2ac23e6` (T3), `85de636` (T4 Mac), `a612191` (T5, T6 Mac), `f2654e7` (gate script), `06a7398` (T7 Mac), `a66db6c` (T8 Mac), `c8883ed` (context contract, default off, README). Publishing waits for Zach's approval in the Mac chat.
- Full suite on Mac: 486 tests OK, 18 skipped. `spikes/writer_gate.py` in TextEdit after the context change: rewrite in place, Undo, and clipboard kept all pass.
- Accepted and done in `c8883ed`:
  1. Mutations take the captured Context: `replace(text, ctx)`, `type_at_caret(text, ctx)`, `select_back(n, ctx)`. The mixin passes the Context captured at selection (rewrite) or at key down (dictation). Mac refuses unless the same app and window still has an editable, non-secure field focused.
  2. Undo: `select_back(n, ctx)`, then a fresh `capture(True)` checked against the inserted text, then `replace(original, fresh)`. `collapse` is optional. Undo calls it only when the platform defines it, so `win/edit.py` can leave it out.
  3. `settings.DEFAULTS["writer"]` is now `False` until the T9 matrix passes. Dictation follows the same switch.
- Shared host contract. The Mac shapes are the contract, and `win/host.py` can wrap the Windows components to match:
  - `host.edit` module as above, plus `NEWLINE`.
  - `make_toast()` returns an object with `show(message, x, y, actions=(), busy=False)`, `hide()`, `visible`, and a settable `on_hide`. An action is `(title, fn)` or `(title, [(title, fn, checked)])` for a submenu.
  - `make_review()` returns an object with `show(original, rewritten, on_replace, on_copy)`. `on_replace` may be None (Copy only).
  - `esc_watcher(fn)` returns an object with `start()`, `stop()`, and `active`. The mixin starts it while a toast, bar, or rewrite is up and stops it on hide. `fn` runs on the main thread or enqueues.
  - `set_shortcut(name, spec, fn, on_release=None)` for `"rewrite"` and `"dictate"`. An empty spec removes it.
  - `copy_text(text)`, `pick_mode(names, current, pick)`, `mic_permission(then)` (calls `then(bool)` through the `("call", fn)` event), `mic_status()` returning `ready|not_asked|denied`, and `open_mic_settings()`.
  - `make_popup(speed, ..., on_rewrite=fn(text, mode_name), modes=fn() -> names, on_escape=fn)` when `writer_ready`. The popup provides `show(text, x, y, editable=False)`, `set_editable`, `set_last_mode`, `set_rewriting`, `anchor() -> (x, y, h)`, and `visible`.
- Settings data for your `SettingsWindow` suppliers: `app.refresh_writer()` fills `app.writer_statuses`, `app.stt_statuses`, and `app.writer_models` (name to `[{"id", "label"?, "efforts"}]`) on a worker, then posts `("writer_info",)`, which calls `settings_win.refresh_writing()`. Fixes go through `app.fix_writer(name, stt=False)`. So `writer_catalogs=lambda: app.writer_models`, `writer_statuses=lambda: app.writer_statuses`, `on_writer_fix=app.fix_writer`, `dictate_status=host.mic_status`. The Mac Settings recorder already pauses the hook being recorded through `app.apply(key, "")`. Windows should do the same for all three keys.
- Windows Cursor: `llm_cursor.agent_exe()` finds no bare executable on Windows, so `CursorWriter.status()` reports `missing` there and the chain skips Cursor. That keeps it unavailable until a live Windows rewrite passes. The `authenticate(cursor_login)` handshake waits for that live check.
- Mac pasteboard reader (`_copy_selection`) ownership: acknowledged. It is pre-existing reading behavior, not Writer. Logged for Zach. Not changed here.
- Remaining: Windows host wiring to this contract, the T9 matrix on both platforms, the dictation gate (DoD 4) with a signed Mac build, and the default flip after the matrix.

### 2026-10-21 Mac (published, PR #60)

- Published to `feat/add-snapdraft-harness-discussion` as PR https://github.com/tzachbon/harness-discussion/pull/60 (Zach asked to create, babysit, and merge it). Mac and shared commits: `92461e6`, `2ac23e6`, `85de636`, `a612191`, `f2654e7`, `06a7398`, `a66db6c`, `c8883ed`, `f668a50`, and the fix commit after this entry. Windows commits through `8b6df99` are kept. No force push.
- Decisions, as in the entry above: mutations take the captured `ctx` (rewrite and dictation), Undo follows the guarded order with an optional `collapse`, the Mac host shapes are the shared host and UI contract, and `writer` stays off by default until the matrix passes.
- Added from PR review: `edit_logic.Context` gained an optional `field` (compare=False) for the platform's focused-element handle. Mac refuses any edit unless that same field is still focused. `win/edit.py` keeps its own Context and is unaffected. Local rewrites refuse a reply cut off at the token limit.
- Windows-owned test touched: `tests/test_win_writing_settings.py` now expects the Writing switch to turn the Writer on, since the default is off. `App._close_writer` returns early when `_init_writer` never ran, which fixes `test_update_app` on Windows CI.
- Remaining blockers: Windows host wiring to the contract, the T9 matrix on both platforms, the Mac dictation gate with a signed build, and the default flip after the matrix.

### 2026-10-21 Mac (PR #60 review round 2)

- `22b22ec`: Windows Writer defaults are now `<ctrl>+<shift>+e` and `<ctrl>+<shift>+d` in `hotkeys.py`, because AltGr sends Ctrl+Alt (AltGr+E is € on many layouts). `win/writing_page.py` `PLAN_DEFAULTS` now reads from `settings.DEFAULTS`, which drops its stale `writer: True`. `tests/test_win_writing_settings.py` follows the new defaults.
- For Windows to decide: CodeRabbit asks `win/selection.py` `_safe_controls` to treat an unsupported `IsPasswordProperty` on unrelated ancestors as non-password, while still requiring an explicit value on the focused control and the `TextPattern` owner. Mac declined it in the PR as Windows-owned and fail-closed. Change it in a later PR if you agree.
- Mac `_paste` now restores the pasteboard only after the focused field's range or length changes (up to 1 s). Cursor timeouts send `session/cancel`.
