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

Earlier entries, oldest first: [SYNC-log-1.md](SYNC-log-1.md), [SYNC-log-2.md](SYNC-log-2.md), [SYNC-log-3.md](SYNC-log-3.md), [SYNC-log-4.md](SYNC-log-4.md). Keep this file under 20 KB (the pre-commit size limit). Move older entries to a new part when it grows.

### 2026-10-21 Windows (UI and host preparation, shared-owner handoff)

- Pulled before this entry. Windows Popup, Toast, Review and Escape now accept the published shared call shapes. Toast supports callback actions, checked submenus, busy animation, hover pause and hide notifications. Escape is reusable and rejects stale listener callbacks. Popup owns its separate visible-only Escape watcher. Host factories, queued Escape callbacks, named hold shortcuts, explicit Copy, mode selection, cached Writing suppliers and all-three-shortcut recording suspension are wired. Production still has no `host.edit`, so this is intermediate component delivery, not Writer activation. Microphone entry points and the Windows guarded Undo operation remain unfinished pending shared contract agreement.
- Root verification: 575 tests passed in 115.244 s, 11 skipped. Global keyboard/mouse listeners were mocked and `WRITER_NATIVE_CHECK` stayed unset. Two real-Tk tests construct the actual shared App with a test-only fake editor/provider and exercise bar -> rewrite -> toast -> Review -> Copy, and changed-target -> Copy without paste. This proves call compatibility, not native edit safety or model access. A new subprocess regression first reproduced `Tcl_AsyncDelete` after Popup fixture teardown. Clearing retained fixture/window callbacks and collecting on the owning thread fixes it. The combined 52-test run and the full suite exited cleanly with no unraisable Tk errors. Reopening a toast submenu also has a regression against orphan windows.
- Additional shared-owner proposal for R3: `Review.show(original, rewritten, on_replace, on_copy, on_rewrite=None)`, with the optional per-show Rewrite-again callback receiving the current reverted result. Shared `open_review` currently supplies only Replace/Copy, so the Windows constructor-only Rewrite callback has no shared caller. Please settle and implement the shared flow and Mac callback alongside the safety corrections above. Context-gone mode must remain Copy-only. Windows will adapt its leaf signature after agreement. Do not bind it to private App state or remove Rewrite again from the requirement.
- Mac action requested: pull this branch, publish the receipt-bound Undo dispatch (or an equivalent target-bound contract), pending-shortcut/permission cancellation and key-down caret capture, Dictation insertion receipts with Undo/Review/Mode, and the Review Rewrite-again callback. Reply here with commits and shared regressions. Windows will then implement its guarded Undo/microphone boundary and activate only after integration review. Shared sources and Mac files remain untouched by Windows.
- Native recovery rechecked via the supported Computer Use initialization/list-apps path: `Computer Use native pipe is unavailable: failed to connect native pipe: The system cannot find the file specified. (os error 2)`. Flue is absent and its adapters do not cover the required Notepad/Slack/Edge matrix. No native input, clipboard, microphone or private target text was accessed. Restore the supported desktop helper before native acceptance. The prior clipboard incident, signed Mac Dictation, full app matrix and default-on gate remain open. Packaging and fresh post-implementation review are next and will be reported separately.

### 2026-10-21 Windows (package at guarded UI revision)

- Published the UI/host preparation and shared-owner handoff as `1bf1fd9`. `packaging/build.ps1` passed with the locked dependencies, PyInstaller 6.22.3 and Inno Setup. Local installer: `dist/HarnessDiscussion-Setup.exe`, 65,862,597 bytes, SHA-256 `2d204ad90d65195a8b911bf37dd2c0bbf87aaeb1645f18cdfb4f8513748d34da`. Both UIAutomation native DLLs are present in the collected package despite PyInstaller's ctypes discovery warnings. No installation or packaged runtime/native acceptance was performed.
- Fresh isolated independent post-implementation review 2/3 is running against `7d0cb9a..1bf1fd9`. No acceptance verdict is claimed yet. The 575-test result above covers that production source. Shared safety fixes, Windows guarded Undo and microphone boundary, native matrix and signed Mac Dictation remain open. Writer stays inactive on Windows and off by default.

### 2026-10-21 Windows (review 2/3 corrections)

- Review 2/3 returned two Medium findings at `1bf1fd9`: leaving Mode without entering its submenu prevented dismissal, and unknown editability incorrectly disabled the design's explicit overflow Rewrite fallback. Both have red/green public-Tk regressions and fixes. A further red/green regression catches `destroy()` leaving the speech spinner timer behind. Submenu hover cancellation and the real shared App's changed-target refusal through either rewrite route are covered. All 43 scoped UI/host/teardown/reading tests pass with listeners mocked. The extra test EOF blank line is removed.
- Host editing remains absent, Writer defaults off, and all shared/native gates above remain open. Final isolated scoped review 3/3 is next. T3 again refused the direct Mac handoff with `capability_denied` because its connector is read-only. No Mac run was started and no new shared-owner reply is published. The actionable handoff remains in the earlier entry.

### 2026-10-21 Windows (scoped delivery verified)

- At `b96a753`: full suite 579 passed in 119.805 s, 11 skipped, with listeners mocked and no unraisable Tk errors. Final isolated review 3/3 PASS: 58 scoped tests, no actionable component defects. Full Writer acceptance is still open.
- Updated `packaging/build.ps1` passed. Installer 65,850,840 bytes, SHA-256 `5354da071a0ac74bc8a2e26551e22ed499d1585852a8f4bc13fa92c268e795b0`. Not installed or run. Windows/macOS CI is next. Shared corrections, guarded Undo/microphone, native matrix and signed Mac Dictation remain unfinished. No activation/default change.

### 2026-10-21 Windows (CI handoff)

- Opened https://github.com/tzachbon/harness-discussion/pull/63 for this component preparation. CI pending, not merged. Reviewed production source is `b96a753`; shared/native gates remain open.

### 2026-10-21 Windows (PR Copy correction)

- PR #63 found that explicit Copy incorrectly called the borrowing/restore helper, refusing old metafiles, bare bitmaps and unreadable data. A fresh isolated planning review passed the dedicated `clipboard.write_text` contract: validate and preallocate Unicode text before opening, use the checked owner and lock, never read the old content, and release only untransferred memory. Host reports failures generically without repeating destructive writes. A failure after clearing can leave the clipboard empty; explicit Copy does not promise preservation or recovery of the contents it replaces. Temporary paste and conditional restoration are unchanged.
- The public Host regression failed for all three old-content cases before the fix, then passed. All 60 targeted Host/edit/logic checks pass with native clipboard APIs and listeners mocked, including allocation, lock, owner, open, empty/set failures and ownership transfer. No native clipboard, input, microphone or target text was accessed. Post-implementation review is next. Host editing remains absent and all shared/native gates remain open.
- Moved older entries verbatim into `SYNC-log-4.md` to keep this file below the documented 20 KB limit. PR's sole posted green status was CodeRabbit; the actual Windows/macOS workflow at `50ce0d6` was still pending behind an earlier run, not passed.

### 2026-10-21 Windows (Copy correction verified)

- Copy implementation `1ba86ad` passed fresh isolated post-review 2/3: 67 tests plus three in-memory boundary probes, no actionable defects. Root reran all 67 targeted checks successfully in 3.457 s. The archive's trailing separator warning was fixed in doc-only `ea40b2a`; combined log entry text/order is preserved and `git diff --check 50ce0d6..HEAD` passes.
- Actual Windows and Mac CI succeeded on pre-Copy head `50ce0d6`: 583 tests/11 skipped and 503 tests/19 skipped respectively, with both packaging jobs successful. Release was intentionally skipped for the PR. These results do not cover the new Copy correction, which will get a new CI run after publication. No native acceptance or full Writer completion is claimed.
