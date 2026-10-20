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
