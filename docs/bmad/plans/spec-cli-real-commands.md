---
title: 'Resolve G1 — make the testvibe CLI stubs real (3) + honest (3)'
type: 'feature'
created: '2026-08-02'
status: 'done'
review_mode: 'self-review'
baseline_commit: 'f620a7d'
baseline_tests: '95 passed (venv at /home/claudedev/testvibe/.venv; run via `. .venv/bin/activate && python -m pytest`)'
context:
  - '{project-root}/docs/bmad/plans/phase-d-trial-checklist.md'
  - '{project-root}/docs/PLAYBOOK.md'
assumptions:
  - '[interpretation] scope = G1 CLI stubs only, not the Phase D external-tool trial — user chose "Implement the G1 CLI stubs" (foreign repo not accessible here)'
  - '[inferred-requirement] dogfood/canary/autopilot stay as honest exit-3 "needs real host/agent" stubs, not fake "done" — fable anti-fraud rule'
  - '[interpretation] corpus write fns live in corpus.py (root fix), mcp.py refactored to delegate — user chose "In corpus.py (root fix)"'
  - '[default-config] plan auto-approved (no human gate after the plan phase)'
  - '[inferred-requirement] promote_entry(passes: bool) — passes=False is a no-op (status unchanged, returns entry as-is), NOT an error — because the caller may be probing; passes=True is the only path to fixed. LOGGED per spec instruction.'
  - '[interpretation] promote_entry raises CorpusError on missing id / missing corpus file — a missing id is a real caller bug, not something to swallow silently (differs from the MCP surface which degrades to a not-found JSON marker, because the CLI is a human-facing tool that should fail loud).'
  - '[interpretation] promote_entry works on both open AND pinned status (not pinned-only) — the PLAYBOOK invariant is "only after green," not "only pinned." An open entry that re-runs green is also fixed.'
  - '[default-config] corpus add auto-generates id as "entry-<uuid hex[:12]>" when --id omitted (mirrors the MCP run_id pattern); source="cli" tag distinguishes CLI-added rows from MCP-added (source="mcp").'
  - '[default-config] run command --cwd defaults to None (current working directory) — matches mcp.run_scenario cfg_cwd=None semantics.'
  - '[interpretation] run tri-state mapping: passed->0, product-failure->1, infra-only-failure->2. If a report has both product AND infra failures, product takes precedence (rc 1) because a product bug is the actionable signal.'
  - '[workaround] mcp.run_scenario reconstructs the advisory transcript from report.failures[0].detail on failure (run_scenarios stores FULL combined stdout+stderr there, not the [-4000:] tail — P5 dropped the truncation so advisory.analyze sees the whole transcript as it did pre-refactor); on pass the transcript is empty. Avoids changing RunReport to carry raw output (bigger surface than this task).'
  - '[interpretation] test_cli_unimplemented_subcommands_return_nonzero in tests/test_init.py updated from asserting "not implemented" on `run` to asserting exit-3 + no-"not implemented yet" on dogfood/canary/autopilot — because the spec redefines `run` from stub to real command; the old assertion tested behavior the spec explicitly changes.'
  - '[behavior-fix] P5: run_scenarios now stores the FULL combined output in Failure.detail (was combined[-4000:]). Failure.detail in report.py has no size cap (only kind is validated in __post_init__), so full output passes through. to_json/to_markdown redact secrets but do not truncate. Assumption: real-world pytest output fits in memory — no failure has exceeded this in practice.'
  - '[behavior-fix] P2: _load_raw_rows now raises CorpusError on a present-but-corrupt file (was: silently returned []), so add_entry/promote_entry refuse to overwrite a broken corpus. promote_entry already raised CorpusError on missing file via its own p.exists() check, so the corrupt-file path now also raises — consistent with load_corpus which already raised on these shapes.'
  - '[behavior-fix] P8: add_entry validates entry.status in (open, pinned) and raises CorpusError otherwise. promote_entry is NOT changed (it legitimately sets fixed). The MCP add_corpus_entry tool passes status through to add_entry, so an MCP caller passing status=fixed now gets CorpusError instead of a silent invisible row.'
  - '[test-strengthening] P4: test_cli_corpus_promote_unknown_id_is_nonzero tightened from `rc != _RC_PASS` to `rc == _RC_INFRA` — CorpusError maps to exit 2 per the CLI tri-state contract, matching the run command assertion pattern.'
  - '[test-fix] P3: three honest-stub tests had a double capsys.readouterr() making the `assert "not implemented yet" not in combined` check vacuously pass (the second call returns empty). Fixed to single capture. Confirmed the stub messages genuinely do NOT contain "not implemented yet" — all 3 tests still pass.'
  - '[behavior-fix] Patch A: CLI corpus promote now executes the entry repro BEFORE promote_entry and returns rc=1 (product) if it raises — was hardcoded passes=True (I/O matrix + PLAYBOOK violation).'
  - '[behavior-fix] Patch B: run_scenarios catches OSError (bad --cwd) -> infra, was uncaught (FileNotFoundError/PermissionError propagated as a traceback, contradicting the documented exit-2 infra contract).'
  - '[behavior-fix] Patch C: quarantine_tests_for wraps per-entry repro load in try/except and SKIPS broken entries (warns to stderr) — was eagerly loading all repros in a comprehension, so one broken repro aborted the whole quarantine collection.'
  - '[behavior-fix] Patch D: add_entry rejects duplicate ids (raises CorpusError) — was appending, creating duplicate pytest test names + zombie pins.'
  - '[architecture] Patch E: add_entry uses dataclasses.asdict(entry) for the row dict — was a hand-built 6-key dict that silently dropped any new CorpusEntry field on write.'
  - '[behavior-fix] Patch F: _load_raw_rows raises CorpusError on a non-dict row — was silently stripping them via isinstance filter, contradicting the fail-loud-on-corrupt behavior shipped for malformed YAML.'
  - '[architecture] Patch H: Failure.detail bounded again at [-4000:] (reverts the unbounded-growth regression from P5); the FULL combined output is stored on report._full_output (a private instance attribute, NOT a RunReport dataclass field, so to_json/to_markdown surface is unchanged) and mcp.run_scenario reads it for the advisory transcript. Chose private-attr over a new RunReport field to avoid changing the class/JSON surface.'
  - '[behavior-fix] Patch I: TimeoutExpired handler now keeps exc.stderr (was discarding it); a negative returncode (signal death, e.g. -9) appends "killed by signal N" to the failure detail and classifies as infra.'
  - '[behavior-fix] Patch J: mcp.promote_corpus classifies CorpusError into corpus_missing / not_found / corpus_corrupt (was unconditionally not_found) via message inspection in _classify_corpus_error helper; unknown shapes fall back to corpus_error (never a raise).'
  - '[behavior-fix] Patch K: mcp.add_corpus_entry wraps add_entry in try/except CorpusError and returns a structured {error, message} dict — was propagating as an RPC exception, unlike promote_corpus.'
  - '[behavior-fix] Patch L: add_entry validates the id against ^[A-Za-z_][A-Za-z0-9_-]*$ (raises CorpusError otherwise) — quarantine_tests_for builds test_quarantine__{id} with only - -> _ substitution, so unsafe chars yield invalid pytest identifiers.'
  - '[behavior-fix] Patch M: CLI corpus add uses repro.is_file() not repro.exists() — a directory passed as --repro was accepted (dir.exists() is True).'
  - '[test-fix] Patch N1: test_mcp discovered_at tightened to assert == today.isoformat() + fromisoformat parses (was truthy-only).'
  - '[test-fix] Patch N2: test_mcp promote-unknown-id pinned to error=="not_found" exactly (was a vacuous `or` disjunction); test now seeds the corpus first so the file exists, isolating unknown-id from missing-file (which patch J classifies as corpus_missing).'
  - '[test-fix] Patch N3: added test_run_scenarios_name_filter_excludes_others — the NEGATIVE case (selecting one scenario must NOT collect a non-substring sibling); the original test only proved inclusion.'
  - '[test-fix] Patch N4: test_init unimplemented-stubs tightened from rc != 0 to rc == 3 (_RC_NEEDS_HOST_AGENT).'
  - '[test-fix] Patch N5: test_cli missing-repro tightened from a 3-way `or` (the bare word "repro" matched anything) to assert the filename or "not found" appears.'
review_mode: ''
research_mode: 'skipped'
research_notes: []
fraud_verdict: 'VERIFIED WITH CAVEATS'
fraud_notes:
  - 'pytest -q re-run by main thread: 160 passed, exit 0 (claim was 160 green) — VERIFIED'
  - 'ruff check src/testvibe exit 0; mypy src "Success: no issues in 15 source files" exit 0 — VERIFIED'
  - 'git grep "not implemented yet" src/testvibe/cli.py → exit 1, zero matches (AC met) — VERIFIED'
  - 'patch A (promote green-check) exercised end-to-end through real CLI: repro-still-raises → rc=1 + status stays open + "not promoted" msg; repro-fixed → rc=0 + status=fixed. The frozen-matrix/PLAYBOOK violation is genuinely closed — VERIFIED'
  - 'patch B (bad cwd→infra) exercised end-to-end: `run --cwd /nonexistent` → rc=2, no traceback leaked — VERIFIED'
  - 'weakened-test scan: the 8 `assert True` hits are FIXTURE DATA (bodies of synthetic passing scenarios written to temp files as runner input), not test assertions. Real assertions (report.passed, rc==_RC_PRODUCT) are present. False positive adjudicated — VERIFIED'
  - 'no debris (.bak/.orig/.tmp none) and no debug print() added to src/ — VERIFIED'
  - 'CAVEAT: the MCP code path (run_scenario delegation, add_corpus_entry structured-error parity, promote_corpus classification) is covered by passing unit tests but NOT independently exercised through a live fastmcp session by the fraud-check (no running MCP server in this run). Trust rests on the unit suite, not a live probe.'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Gap G1 — the plan documents `cli.py` with working `run`, `corpus {add,promote}`, `dogfood`, `canary`, `autopilot` commands, but the code ships them as exit-2 `_not_implemented` stubs. The documented CLI surface does not match reality.

**Approach:** Implement the 3 commands with a clean deterministic path (`run` = S0 pytest gate; `corpus add`/`promote` = new corpus.py write fns reusing the mcp._dump_raw_yaml pattern), moving the write half into corpus.py where its docstring promises it. Rewrite the 3 host/agent-dependent commands (`dogfood`/`canary`/`autopilot`) as honest exit-3 "needs real host/agent" stubs instead of the misleading "not implemented yet."

## Boundaries & Constraints

**Always:** TDD (RED→GREEN→REFACTOR) for every production task. Reuse the existing `mcp.run_scenario` pytest-subprocess + tri-state-exit-code pattern and `RunReport`; do not reinvent. corpus.py becomes the single mutation path for `known-failures.yaml` (mcp.py delegates to it).

**Ask First:** none — all design decisions resolved at plan time.

**Never:** fake a working `dogfood`/`canary`/`autopilot` (no hermetic path exists; would be REFUTED by step-04c). Never edit `src/**` outside the files in the Code Map. Never add new runtime dependencies (stdlib + existing pyyaml only).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| `run` all-pass | repo with hermetic `@scenario` tests | pytest rc 0, markdown report printed, CLI exits 0 | N/A |
| `run` product-fail | a scenario assertion fails | pytest rc 1, report with `kind=product` failure, CLI exits 1 | rc 1 = product, not infra |
| `run` infra-fail | collection error / no tests / timeout | pytest rc 2/3/5 or TimeoutExpired, `kind=infra`, CLI exits 2 | non-1 non-zero + timeout → infra |
| `corpus add` | repro path + invariant + source | new row appended, status open, reloadable | missing repro file → non-zero + message |
| `corpus promote` | id that exists + green re-run | status pinned→fixed | id not found / re-run not green → non-zero |
| `dogfood`/`canary`/`autopilot` | any args | exit 3 + "needs real host/agent" message | NOT "not implemented yet" |

</frozen-after-approval>

## Code Map

- `src/testvibe/corpus.py` — add `add_entry(path, entry)`, `promote_entry(path, entry_id, *, passes)`, `_dump_corpus(path, rows)`. Reuse `load_corpus`, `CorpusEntry`, `CorpusError`, `_REQUIRED_FIELDS`.
- `src/testvibe/_run.py` (new, small) — `run_scenarios(cwd, name=None) -> RunReport`, extracted from `mcp.run_scenario` (mcp.py:145-211).
- `src/testvibe/cli.py` — `_cmd_run`, `_cmd_corpus_add`, `_cmd_corpus_promote`; rewrite 3 honest stubs via `_needs_host_agent(name)` returning 3.
- `src/testvibe/mcp.py` — `run_scenario` delegates to `_run.run_scenarios`; corpus-append tool calls `corpus.add_entry`; remove superseded `_dump_raw_yaml` (mcp.py:65).
- `tests/test_corpus.py` — extend: add/promote round-trip, promote-after-green, id-not-found.
- `tests/test_run.py` (new) — `run_scenarios` tri-state exit mapping + cwd.
- `tests/test_cli.py` (new) — dispatch tests for all six commands, `cli.main([...])` + assert-on-rc pattern.

## Tasks & Acceptance

**Execution (TDD — tests first, always):**

**1. corpus write fns (root fix)**
- [x] `tests/test_corpus.py` -- test: `add_entry` appends a row that `load_corpus` reloads (round-trips CorpusEntry fields); `promote_entry` flips pinned→fixed only after a green signal, errors on missing id
- [x] `src/testvibe/corpus.py` -- implement: `add_entry`, `promote_entry`, `_dump_corpus` (yaml.safe_dump sort_keys=False) -- verify: `pytest tests/test_corpus.py` all green -- closes the read/write drift the docstring promised

**2. corpus mutation single-path (mcp refactor)**
- [x] `tests/test_mcp.py` -- test: corpus-append MCP tool now routes through `corpus.add_entry`; existing MCP corpus assertions still hold
- [x] `src/testvibe/mcp.py` -- refactor: append tool calls `corpus.add_entry`; drop `_dump_raw_yaml` if fully superseded -- verify: `pytest tests/test_mcp.py` all green -- single mutation path

**3. shared run orchestrator**
- [x] `tests/test_run.py` -- test: `run_scenarios` shells `pytest -m testvibe_scenario`; rc 0→passed, 1→product, else/timeout→infra; respects cwd
- [x] `src/testvibe/_run.py` -- implement: `run_scenarios(cwd, name=None) -> RunReport`, pattern lifted from mcp.run_scenario (mcp.py:145-211) -- verify: `pytest tests/test_run.py` green
- [x] `src/testvibe/mcp.py` -- refactor: `run_scenario` delegates to `_run.run_scenarios` -- verify: `pytest tests/test_mcp.py` green -- no behavior change

**4. CLI wiring + honest stubs**
- [x] `tests/test_cli.py` -- test: `run` returns pytest rc + prints report; `corpus add/promote` work; `dogfood`/`canary`/`autopilot` exit 3 with "needs real host/agent" (not "not implemented yet")
- [x] `src/testvibe/cli.py` -- implement: `_cmd_run` (calls `_run.run_scenarios`, prints `to_markdown`, maps pass/product/infra → 0/1/2), `_cmd_corpus_add`, `_cmd_corpus_promote`, `_needs_host_agent` -- verify: `pytest tests/test_cli.py` green -- documented CLI surface matches reality

**Acceptance Criteria:**
- Given hermetic `@scenario` tests, when `testvibe run`, then it runs `pytest -m testvibe_scenario` and exits 0 iff all pass (PLAYBOOK S0 gate).
- Given a repro, when `testvibe corpus add ...` then a row appears; `testvibe corpus promote <id>` after green sets `status: fixed`.
- Given `testvibe dogfood`/`canary`/`autopilot`, then exit 3 with a real-prerequisite message.
- Given `git grep -n "not implemented yet" src/testvibe/cli.py`, then zero matches for the 3 now-real commands.

## Verification

**Commands:**
- `pytest tests/test_corpus.py tests/test_run.py tests/test_cli.py tests/test_mcp.py -q` -- expected: all green
- `pytest -q` -- expected: full unit suite green (existing + new)
- `ruff check src/testvibe && mypy src` -- expected: clean
- `python -c "from testvibe.cli import main; import sys; sys.exit(main(['run']))"` in a scenarios-bearing dir -- expected: runs S0 gate, exits with pytest's code

## Spec Change Log

(empty until first review loopback)

## Suggested Review Order

**Entry point — the CLI dispatch surface (start here)**

- Six subcommands now resolve to real handlers; this is the contract the change delivers.
  [`cli.py:181`](../../src/testvibe/cli.py#L181)

**Promotion correctness (the highest-stakes behavior)**

- `corpus promote` executes the repro and refuses `fixed` unless it passes — the PLAYBOOK green-re-run invariant, enforced at the CLI.
  [`cli.py:106`](../../src/testvibe/cli.py#L106)
- The underlying mutator: `passes=True` is the only path to `fixed`; everything else is a no-op or error.
  [`corpus.py:252`](../../src/testvibe/corpus.py#L252)

**The run orchestrator (shared by CLI `run` and MCP `run_scenario`)**

- pytest subprocess + tri-state exit (0 pass / 1 product / else+timeout+OSError infra); the one place run-semantics live.
  [`_run.py:37`](../../src/testvibe/_run.py#L37)
- CLI `run` maps the report to exit codes 0/1/2 and prints the markdown report.
  [`cli.py:59`](../../src/testvibe/cli.py#L59)

**Corpus mutation safety (the data-loss defenses review forced)**

- Atomic write (temp + `os.replace`); an interrupted write can no longer truncate the corpus.
  [`corpus.py:138`](../../src/testvibe/corpus.py#L138)
- Fail-loud loader: corrupt YAML / non-dict rows raise instead of silently degrading to `[]` (prevents silent overwrite on `add`).
  [`corpus.py:172`](../../src/testvibe/corpus.py#L172)
- `add_entry`: rejects duplicate ids, validates id charset + status, writes via `dataclasses.asdict`.
  [`corpus.py:207`](../../src/testvibe/corpus.py#L207)
- Broken repro degrades to a per-entry skip instead of aborting the whole quarantine collection.
  [`corpus.py:295`](../../src/testvibe/corpus.py#L295)

**Honest stubs + MCP parity**

- dogfood/canary/autopilot exit 3 with a real-prerequisite message (not "not implemented yet").
  [`cli.py:152`](../../src/testvibe/cli.py#L152)
- MCP corpus tools return structured classified errors (corpus_missing / not_found / corpus_corrupt) and delegate to the same `corpus.*` chokepoint.
  [`mcp.py:45`](../../src/testvibe/mcp.py#L45)

**Tests (peripheral — read last)**

- CLI dispatch + tri-state + promote-green-check + honest-stub exit-3.
  [`test_cli.py`](../../tests/test_cli.py)
- run_scenarios tri-state (incl. OSError-cwd, timeout, signal-death, name-filter exclusion).
  [`test_run.py`](../../tests/test_run.py)
- corpus mutation safety (atomic/fail-loud/dup-id/charset/broken-repro).
  [`test_corpus.py`](../../tests/test_corpus.py)
