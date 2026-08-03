# Deferred work

Items surfaced by review but intentionally deferred (pre-existing, out of current
scope, or design judgment — not caused by the current change's acceptance criteria).
Each is real; none were silently dropped.

## From G1 CLI-stubs review (2026-08-02, branch `feat/cli-real-commands`)

- **RESOLVED 2026-08-02 (D1) — repro-path arbitrary-code-execution vector
  (security, pre-existing).** `_load_repro` now accepts an optional `base` and
  confines repro paths to it (resolves symlinks; rejects absolute/relative
  escapes via `Path.is_relative_to`). `add_entry` enforces confinement at write
  time too AND stores the repro RELATIVE to the corpus dir when colocated (so it
  re-resolves confined on reload). `quarantine_tests_for(base=...)` and the
  pytest plugin pass the corpus file's parent dir as base; an escaping repro is
  skipped (not executed). `base=None` preserves the legacy unconfined path for
  direct callers. (Edge-case hunter + blind hunter.)
- **RESOLVED 2026-08-02 (D2) – `_cmd_run` multi-kind branch is dead code.**
  Simplified to single-failure mapping: `passed`->0, `kind=="product"`->1,
  else ->2. `run_scenarios` adds at most ONE Failure, so the former set logic
  never fired. Behavior identical; existing run tests define the contract.
  (Blind hunter + acceptance auditor.)
- **RESOLVED 2026-08-02 (D3) – CLI `corpus promote` exit code conflates
  usage-error with infra.** Added `_RC_USAGE=4` for caller/usage errors (wrong
  id, missing/corrupt corpus); `CorpusError` now maps to rc 4 (was rc 2). Genuine
  `OSError` during read/write still maps to rc 2 (infra). Documented the now-5-
  code taxonomy (0/1/2/3/4) in the cli.py module docstring. (Blind hunter +
  acceptance auditor + edge-case hunter.)
- **RESOLVED 2026-08-02 (D4) – corpus mutation is O(n) read-modify-write with
  no file lock.** `_with_corpus_lock` (fcntl.flock LOCK_EX on `<path>.lock`)
  wraps the read-modify-write in `add_entry` + `promote_entry`, serializing
  concurrent writers (no lost update). `fcntl` is Unix-only; guarded with
  try/except ImportError so non-Unix degrades to a no-op (project targets Linux).
  (Blind hunter + edge-case hunter.)

## From the original Phase D checklist (docs/bmad/plans/phase-d-trial-checklist.md G3)

- **PARTIALLY RESOLVED 2026-08-03 (D5) — Embedded GitHub PAT in `origin` remote URL.**
  Local half done: `remote.origin.url` rewritten from
  `https://ghp_30qiSf…@github.com/assaads/testvibe` to the token-free
  `https://github.com/assaads/testvibe.git` (verified: `.git/config` has no `ghp_`
  token). The token was confirmed to live ONLY in local `.git/config` — never in
  git history or tracked files — so no history rewrite (BFG/filter-repo) was
  needed. A global `credential.helper=store` supplies credentials at runtime
  (from `~/.git-credentials`, mode 0600), never embedded in the URL.
  **PENDING (human action — cannot be automated):** the exposed token
  `ghp_30qiSf…` MUST be rotated/revoked in GitHub (Settings → Developer settings
  → Personal access tokens). `~/.git-credentials` still holds the old token and
  will be rejected after rotation; the next `git push` will prompt for the new
  token. Scrubbing the URL without rotation is not sufficient — the token is
  already exposed. (Security item; tracked in project memory
  `testvibe-remote-embedded-pat`.)
