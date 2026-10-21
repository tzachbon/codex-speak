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

### 2026-10-20 Mac

- Plan approved by Zach. Starting S1 (Cursor RPC spike) on the Mac.
- Windows, first task: report the environment baseline in a new entry:
  Windows version, `uv sync` and unit test result, `codex --version` and `codex login status`, whether Cursor desktop is installed and signed in,
  and the checkout path. No code changes yet.

### 2026-10-21 Windows

- DONE: first assigned task, environment baseline only. Read PLAN.md and all five parts. No code changes.
- Checkout: `C:\Users\ADMIN\Projects\harness-discussion`, branch `feat/add-snapdraft-harness-discussion`, baseline commit `401dfa7`. Pulled before reading and again before this entry, both up to date.
- Windows: Windows 11 Pro 25H2, x64, version `10.0.26200`, build `26200.9711`.
- `uv sync`: PASS (exit 0), created `.venv` with CPython `3.11.0` from `C:\Program Files\Python311\python.exe`. uv version `0.11.32`. No tracked dependency-file changes.
- `uv run python -m unittest discover -s tests`: FAIL (exit 1), 404 tests in 85.929 s, 3 errors and 7 skips. Errors are `test_summarize.DownloadTest.test_a_tampered_model_leaves_nothing_that_looks_ready`, `test_a_verified_download_is_ready_and_remove_deletes_it`, and `test_an_archive_that_escapes_its_folder_is_refused`.
- Test blocker: `summarize.py:140` calls `TarFile.extractall(..., filter="data")`, which this interpreter rejects, then line 141 references the unavailable `tarfile.FilterError`. Confirmed by introspection: `extractall` has no `filter` parameter and `tarfile` has no `FilterError`. Shared code left untouched. Proposal for Mac: establish a compatible Python baseline while preserving safe archive filtering.
- `codex --version`: `codex-cli 0.160.1`. `codex login status`: `Logged in using ChatGPT`.
- Cursor desktop: no installation found in standard per-user/system install locations, uninstall/App Paths registry records, Start menu entries, PATH, or running processes. A portable/nonstandard installation remains unverified. Residual `%APPDATA%\Cursor\User\globalStorage\state.vscdb` exists, but the app's read-only `cursor_auth.status()` returns `expired`. A usable signed-in desktop session is not confirmed. No tokens or account details were printed, and no sign-in was attempted.
- Blockers for later Windows gates: failing unit baseline on Python 3.11.0 and no confirmed usable Cursor desktop session. No Writer runtime checks attempted in this baseline task.
- Zach: approve a push of this Windows baseline commit to `origin/feat/add-snapdraft-harness-discussion`? Stopping after the local commit until approval or the next assignment in this log.

### 2026-10-21 Windows

- Zach approved the baseline push and explicitly removed the need to ask before future pushes for this Writer work: "Yes, you don't need to ask me anymore. You just need to coordinate with another T3 chat. Can you find it?" This supersedes the earlier per-push approval requirement for this work.
- Windows T3 chat: `0232746c-0bf1-441b-ae8c-e0224ac677da` (Implement Windows Writer Support), link `t3-thread://v1/0232746c-0bf1-441b-ae8c-e0224ac677da`.
- Direct chat discovery is blocked: the available T3 servers identify as Tzach-PC (Windows) and srv1630226 (Linux). The Windows harness-discussion project lists only this Windows chat, and the VPS has no registered harness-discussion project. Neither available connection exposes the Mac environment, so no Mac thread was identified or messaged.
- Mac: please pull the Windows baseline commit `50a7651`, review the Python and Cursor blockers above, and append your T3 thread link plus the next Windows assignment here. SYNC remains the coordination record. No additional implementation started.
