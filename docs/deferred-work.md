# Deferred work

Items surfaced by review but intentionally deferred (pre-existing, out of current
scope, or design judgment — not caused by the current change's acceptance criteria).
Each is real; none were silently dropped.

## From G1 CLI-stubs review (2026-08-02, branch `feat/cli-real-commands`)

- **repro-path arbitrary-code-execution vector (security, pre-existing).**
  `_load_repro` (`src/testvibe/corpus.py`) executes any caller-supplied path via
  `importlib` — no confinement to the repo root. `add_entry`/`--repro`/MCP
  `repro_path` all accept arbitrary strings. A malicious/confused agent can pin a
  repro that runs arbitrary code on every pytest collection. This surface predates
  G1 (`_load_repro` always exec'd); the G1 change only stores the string. Fix:
  validate repro resolves inside the project root; consider a sandbox. Tracked also
  for a LeaFS entry. (Edge-case hunter + blind hunter — `escalate`/`defer`.)
- **`_cmd_run` multi-kind branch is dead code.** `run_scenarios` adds at most one
  `Failure`, so the `kinds == {'infra'} or (kinds and 'product' not in kinds)`
  precedence logic in `cli.py` never fires. Harmless but misleading. Simplify to a
  single-kind mapping when refactoring. (Blind hunter + acceptance auditor — `defer`.)
- **CLI `corpus promote` exit code conflates usage-error with infra.** A wrong id
  (caller bug) maps to exit 2 (infra) today; retrying won't help. Design judgment:
  a distinct usage-error code or a documented "infra = collection/usage" convention.
  (Blind hunter + acceptance auditor + edge-case hunter — `defer`.)
- **corpus mutation is O(n) read-modify-write with no file lock.** Concurrent
  `corpus add` invocations lose entries (lost-update across appenders); atomic-rename
  protects against truncated-read but not the race. Add `fcntl.flock` around the
  read-modify-write if the corpus ever grows or concurrent capture becomes common.
  (Blind hunter + edge-case hunter — `defer`.)

## From the original Phase D checklist (docs/bmad/plans/phase-d-trial-checklist.md G3)

- **Embedded GitHub PAT in `origin` remote URL** — `git remote -v` leaks a valid
  `ghp_…`. Rotate and move to a credential helper / SSH remote. (Security item;
  tracked in project memory `testvibe-remote-embedded-pat`.)
