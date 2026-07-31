---
title: 'Self-dogfood S0–S7 scenario matrix'
type: 'feature'
created: '2026-07-31'
baseline_commit: '0f0884389eef8bac216b54b84716a152a6394135'
status: 'done'
context:
  - '{project-root}/README.md'
  - '{project-root}/docs/superpowers/specs/2026-07-29-real-usage-testing-design.md'
  - '{project-root}/skills/testvibe-autopilot/SKILL.md'
assumptions:
  - '[default-config] No BMad config.yaml in project → artifacts root = docs/bmad/ (tracked; only root .bmad/ is gitignored). project_name=testvibe, user_name=Assaad, comm/doc lang=English, skill_level=expert.'
  - '[interpretation] "use testvibe to test itself" = build a @scenario self-dogfood suite (user-confirmed Q1), full S0–S7 matrix (Q2), in a new scenarios/ dir with a separate invocation (Q3).'
  - '[default-config] scenarios/ is isolated from the 95-test unit gate by [tool.pytest.ini_options] testpaths=["tests"]; dogfood runs via explicit `pytest scenarios/`.'
  - '[inferred-requirement] Every dogfood scenario runs inside tmp_path / the plugin env fixture — no file materialized under a repo-collected path (avoids the known-failures.yaml collection-collision; plugin collects ANY file of that exact name).'
  - '[interpretation] If a scenario reveals a real testvibe bug: do NOT weaken the test to pass — pin it as a known-failure repro (testvibe S7 discipline) and HALT to ask fix-now vs pin.'
  - '[default-config] plan auto-approved (no human gate after the plan phase) — skill v2 behavior.'
  - '[default-config] oversize spec (~1895 tokens > 1600) kept, not split — full S0–S7 matrix requested; accept context-rot risk.'
  - '[task-harness] scenarios/ uses NO __init__.py (mirrors tests/ convention); absolute `from _helpers import` works because prepend import mode inserts scenarios/ on sys.path. conftest isolation guard asserts no known-failures.yaml under scenarios/ or repo root at session start/end + a collection hook that fails loud on leakage.'
  - '[task-pyproject] Added [tool.pytest.ini_options] testpaths=["tests"]; verified default gate still reports 95 tests with zero scenario collection, and `pytest scenarios/ --co -q` still collects scenarios.'
  - '[task-s0] Mutation-check PASS via two src/testvibe inversions: (a) scrub_env inverted to KEEP prefixed keys → "prefixed key leaked" red; (b) redact made a no-op (`return text`) → ghp_ token present in to_json red. Both reverted, green restored.'
  - '[task-s0-reconfirm] Re-ran mutation via in-process `mock.patch.object` + `pytest.main` (mocks live in-process; subprocess can't inherit them). scrub_env inverted → rc=1 RED; redact no-op → rc=1 RED. PASS.'
  - '[task-s1] Mutation-check PASS: `mock.patch.object(scaffold, "generate", mutant)` where mutant deletes `known-failures.yaml` after the real call → "generate did not write the expected 4 surfaces" rc=1 RED. src untouched.'
  - '[task-s2] Mutation-check PASS: src-mutate `kept = {}` in scaffold.upgrade (drop keep-blocks) → "upgrade dropped a user # testvibe:keep block" rc=1 RED; reverted via `cp /tmp/scaffold.py.bak`, `git diff src/testvibe/` empty, 3 scenarios green restored.'
  - '[task-s3] Mutation-check PASS (two mutations): (a) in-process `mock.patch.object(canary,"with_backoff", mutant)` routing Persistent→infra rc=1 RED; (b) src-mutate scenario.py `if kind != "hermetic"` → `if False` (no skip-mark) → "canary scenario was not skip-marked" rc=1 RED. (b) reverted, green restored.'
  - '[interpretation S3/S4] kind="canary"/"dogfood" scenarios are themselves skip-marked, so their body never runs under `pytest scenarios/`. The skip-semantics are asserted by a separate always-run plain test; the surface behavior (`with_backoff`, `assert_no_regression`) is exercised in always-run plain tests so assertions always run.'
  - '[task-s4] Mutation-check PASS: in-process `mock.patch.object(dogfood,"assert_no_regression", no_op)` (never raises) → pytest.raises "DID NOT RAISE" rc=1 RED.'
  - '[task-s5] Mutation-check PASS: in-process `mock.patch.object(bench,"compare_to_baseline", always_true)` → "value strictly over threshold must be a regression" rc=1 RED.'
  - '[task-s6] Mutation-check PASS: in-process `mock.patch.object(advisory,"analyze", empty_list)` → "expected slow_but_passing ... got set()" rc=1 RED.'
  - '[task-s7] Mutation-check PASS (two mutations): (a) fuzz harness proven load-bearing by running a deliberately-broken-invariant model through `run_state_machine_as_test` → AssertionError "regression: value -1 < 0" (harness is not a no-op); (b) src-mutate corpus.py `load_corpus` to `return []` → "expected 1 open entry, got 0" rc=1 RED. (b) reverted, green restored.'
  - '[interpretation S7] `@rule(n=int)` is invalid Hypothesis (needs a SearchStrategy); used `@rule(n=integers())`. Fuzz scenario runs ~1.7–3.3s (Hypothesis search) — acceptable; marked within tolerance.'
  - '[task-s4b] Mutation-check PASS: src-mutate mcp.py `infra = False` (disable exit!=1 classification, tag all failures product) → infra-vs-product test "infra" vs "product" mismatch rc=1 RED. Reverted, green restored.'
  - '[interpretation S4b] run_scenario uses `<sys.executable> -m pytest` which on this venv is `.venv/bin/python -m pytest` — avoids the broken bare-`pytest` import error. Hermetic scenario project laid under tmp_path; exit-2 broken-import case classified infra per contract.'
review_mode: 'self-review'
research_mode: 'tavily'
research_notes:
  - '[plan] pytest custom markers: register via pytest_configure(config)+addinivalue_line in conftest; pyproject-only can still warn (pytest #10799). testvibe already registers its 6 markers in plugin.pytest_configure — dogfood conftest only registers NEW markers if it introduces any. (src: github.com/pytest-dev, stackoverflow.com)'
  - '[plan] Hypothesis stateful: run_state_machine_as_test(factory, settings=) runs a RuleBasedStateMachine; invariants checked after @initialize by default; API stable 6.15x. S7 subclasses TestvibeStateMachine (__test__=False). (src: hypothesis.readthedocs.io)'
  - '[plan] pytest-benchmark: benchmark fixture callable; --benchmark-compare-fail EXPR (min:5%) CI-enforceable; prefer relative comparisons; .benchmarks/ gitignored. S5 keeps perf off the default gate, asserts compare_to_baseline logic deterministically. (src: pytest-benchmark.readthedocs.io)'
  - '[plan] detect-secrets baseline model (scan > .secrets.baseline; --baseline); report.py redact() masks ghp_/ghs_/AKIA/xox[baprs]- prefixes → ***REDACTED***. S0 asserts redaction on a planted fake token. (src: appsecsanta.com, rafter.so)'
fraud_verdict: 'VERIFIED'
fraud_notes:
  - 'All claims re-derived by observation: 24 passed/2 skipped; gate 95 tests/0 scenarios; ruff+mypy clean; src/testvibe zero diff vs baseline (verified 3x); no known-failures.yaml leak; no debris (.bak/print/pdb).'
  - 'Weakened-test scan hits all false positives: "TODO" in comments+template-strings; `assert True` literal inside generated scenario bodies (test_s4b:40,100); `pytest.skip` is the intentional portability guard in test_s5:64. No real weakening.'
  - 'Anti-no-op keystone load-bearing PROVEN by live mutation this run: (a) S7 _BreakableModel -> test_s7_state_machine_detects_violation raises; (b) S2 stale-body refresh distinguishes working upgrade from no-op; (c) S4b mcp.py:188 `!=1`->`!=999` made test_s4b_mcp_product_failure_classified_as_product RED (product vs infra), reverted -> green, src/testvibe clean.'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** testvibe ships a real-usage testing tool but contains only unit tests — zero `@scenario` real-usage tests. Its central thesis ("unit tests pass but real usage breaks") is therefore unproven on itself, and the S4 self-dogfood surface is empty. A skeptic could rightly ask: does testvibe catch its own real-usage regressions?

**Approach:** Add a `scenarios/` package of `@scenario`-tagged tests — one per surface S0–S7 — that exercise testvibe the way a user drives it (init/upgrade round-trips, the plugin's quarantine auto-pin, the MCP `run_scenario`→report loop, `scrub_env` gating, secret redaction, advisory analysis, the Hypothesis fuzz state machine). Every scenario runs hermetically under `tmp_path` so it never perturbs the 95-test unit gate.

## Boundaries & Constraints

**Always:**
- Every scenario is `@scenario(name, kind="hermetic")` so it runs under `pytest scenarios/`. Canary/dogfood kinds are skip-marked — only their skip-semantics are asserted (in dedicated S3/S4 scenarios).
- Every scenario operates inside `tmp_path` / the plugin `env` fixture. No file is materialized under `tests/` or repo root.
- Each task's `verify:` includes a **mutation check**: invert the tested testvibe behavior, confirm the scenario REDs, revert. Proves the test is not a no-op (anti-fraud; step-04c enforces).
- TDD: write the scenario, run it, observe + record the actual outcome before declaring done.

**Ask First:**
- Any edit to `src/testvibe/*`. Default is test-only. If a scenario reveals a real bug → HALT: ask fix-now vs pin-as-known-failure.
- Any new pytest marker beyond testvibe's existing 6 (`testvibe_scenario, property, perf, live, dogfood, quarantine`).

**Never:**
- Weaken a scenario to make it pass (drop an assertion, loosen tolerance, `assertTrue(True)`) — that is fraud; step-04c refutes it.
- Materialize a `known-failures.yaml` under `tests/` or repo root (plugin collects it globally).
- Add `scenarios/` to the default gate `testpaths` — it stays opt-in via `pytest scenarios/`.
- Assert on real network or wall-clock timing. Perf asserts comparator logic, not absolute ms.

## I/O & Edge-Case Matrix

| Surface | Scenario | Drives (testvibe API) | Expected |
|---|---|---|---|
| S0 | `s0_gate_scrub_and_redact` | `gate.scrub_env("LEAK_")`; `report.RunReport` w/ planted `ghp_`/`AKIA` token | prefixed keys dropped, others kept; token → `***REDACTED***` in `to_json()` |
| S1 | `s1_init_scaffold_roundtrip` | `scaffold.generate(contract, dest=tmp)` | 4 files written with `# testvibe:generated`; `test_s1_boundary.py` collectable as `@scenario` |
| S2 | `s2_registry_and_keep` | `@scenario` registry; `scaffold.upgrade` keep-survival | `SCENARIOS[name]` has correct kind/surfaces; `# testvibe:keep` block survives `upgrade` |
| S3 | `s3_canary_skip_and_backoff` | `@scenario(kind="canary")`; `canary.with_backoff` | canary scenario collected but skip-marked; `Transient`/`Persistent` raised on right inputs |
| S4 | `s4_dogfood_skip_and_telemetry` | `@scenario(kind="dogfood")`; `dogfood` telemetry | dogfood scenario skip-marked; `assert_no_regression` correct on synthetic CPU/RSS samples |
| S5 | `s5_perf_baseline_logic` | `bench.compare_to_baseline`; `bench.scale_tree`/`sparse_file` | True within tolerance, False beyond; fixtures generated deterministically |
| S6 | `s6_advisory_analyze` | `advisory.analyze` on synthetic run data | expected advisory kinds returned (non-blocking) |
| S7 | `s7_fuzz_and_quarantine` | `fuzz.TestvibeStateMachine` subclass; `corpus.load_corpus`/`promote_corpus` on tmp file | fuzz runs clean; open entry loads; promote → `fixed` |
| S4b (meta) | `s4b_mcp_run_scenario_roundtrip` | `mcp.build_server()` in-process; `run_scenario`→`get_run_report` | well-formed JSON report, `passed=True` |

</frozen-after-approval>

## Code Map

- `scenarios/conftest.py` -- NEW: isolation guard (assert no repo-collected `known-failures.yaml` leaks), `env` passthrough, shared synthetic-token/telemetry factories.
- `scenarios/_helpers.py` -- NEW: hermetic fixtures — fake repro module writer, synthetic advisory/telemetry datasets.
- `scenarios/test_s0_gate.py` … `scenarios/test_s7_fuzz.py` -- NEW: one module per surface; `test_s4b_mcp.py` for the meta round-trip.
- `pyproject.toml` -- EDIT: add `[tool.pytest.ini_options]` with `testpaths = ["tests"]` (isolates `scenarios/` from default gate).
- `src/testvibe/*` -- EXISTING API under test; read-only unless a real bug surfaces (→ Ask First).

## Tasks & Acceptance

**Execution (TDD — tests first, always):**

- [x] `scenarios/test_s0_gate.py` -- test: `scrub_env("LEAK_")` drops `LEAK_*` keys / keeps others; `RunReport` redacts `ghp_`/`AKIA` tokens in `to_json()`
- [x] `scenarios/conftest.py` + `scenarios/_helpers.py` -- implement: tmp-scoped `env`, fake-token factory, isolation guard -- verify: `pytest scenarios/test_s0_gate.py -q` exit 0; mutation (invert `scrub_env` keep/drop) → exit 1 -- S0 harness
- [x] `pyproject.toml` -- implement: `[tool.pytest.ini_options] testpaths=["tests"]` -- verify: `pytest --co -q` lists only `tests/` (95-count preserved); `pytest scenarios/ --co -q` lists scenarios -- isolation
- [x] `scenarios/test_s1_scaffold.py` -- test: `scaffold.generate` writes 4 `# testvibe:generated` files into tmp; boundary tmpl is a collectable `@scenario` -- verify: `pytest scenarios/test_s1_scaffold.py -q` exit 0; mutation (drop a file in scaffold list) → exit 1
- [x] `scenarios/test_s2_registry_keep.py` -- test: `@scenario` registers correct kind/surfaces; `# testvibe:keep` block survives `scaffold.upgrade` -- verify: run green; mutation (clear registry on register) → red
- [x] `scenarios/test_s3_canary.py` -- test: `kind="canary"` scenario is skip-marked under `pytest`; `with_backoff` raises `Transient`/`Persistent` on right inputs -- verify: green; mutation (canary not skip-marked) → red
- [x] `scenarios/test_s4_dogfood.py` -- test: `kind="dogfood"` skip-marked; `assert_no_regression` flags RC5-spin signature on synthetic samples -- verify: green; mutation (invert regression predicate) → red
- [x] `scenarios/test_s5_perf.py` -- test: `compare_to_baseline` True within / False beyond tolerance; `scale_tree`/`sparse_file` build fixtures -- verify: green; mutation (flip comparator return) → red
- [x] `scenarios/test_s6_advisory.py` -- test: `advisory.analyze` returns expected advisory kinds for synthetic slow-but-passing / smell data -- verify: green; mutation (empty the analyzer) → red
- [x] `scenarios/test_s7_fuzz.py` -- test: `TestvibeStateMachine` subclass runs clean via `run_state_machine_as_test`; `load_corpus` loads an `open` entry from tmp; `promote_corpus` → `fixed` -- verify: green; mutation (break invariant rule) → red
- [x] `scenarios/test_s4b_mcp.py` -- test: `build_server()` in-process; `run_scenario(<hermetic name>)` → `get_run_report` returns JSON with `passed=True` -- verify: green; mutation (force pytest exit≠0 path tagged infra) → report reflects it

**Acceptance Criteria:**
- Given testvibe installed, when `pytest scenarios/ -q`, then one `@scenario` per surface S0–S7 runs green (canary/dogfood kinds asserted skip-marked) with zero repo pollution.
- Given any dogfood scenario, when its tested testvibe behavior is inverted, then the scenario fails (no-op tests rejected by mutation check).
- Given the default gate, when `pytest -q` runs from repo root, then only `tests/` is collected (95-count preserved); `scenarios/` is excluded.

## Design Notes

**Why mutation-checks, not just green:** testvibe already passes 95 unit tests, so a dogfood scenario will often be green on first run. A green test that stays green when the code is broken is a rubber stamp. Each `verify:` inverts behavior and asserts red — this is the per-task application of step-04c's anti-fraud discipline, done cheaply at write time.

**Why `tmp_path` everywhere:** the plugin's `pytest_collect_file` collects any `known-failures.yaml` pytest walks, and `@scenario(kind=canary|dogfood)` are skip-marked. Running every scenario under `tmp_path` (outside collection, runtime-written) plus direct `load_corpus`/`promote_corpus` calls keeps the suite hermetic and collision-free.

**The recursion is the point:** `s4b` has testvibe's MCP server invoke `pytest -m testvibe_scenario` on testvibe's own scenario — testvibe driving testvibe. Kept to one fast hermetic name so the nested subprocess stays deterministic.

## Verification

**Commands:**
- `pytest scenarios/ -q` -- expected: all dogfood scenarios green (or intentional xfails pinned as known-failures)
- `pytest -q` (repo root, default gate) -- expected: 95 unit tests, count unchanged, `scenarios/` NOT collected
- `ruff check . && mypy` -- expected: clean (`scenarios/` included in lint/type gate)
- per-scenario mutation spot-checks recorded during implementation (see each `verify:`)

## Suggested Review Order

**Isolation (the one-line guardian)**

- Pins the default gate to tests/ only; `pytest scenarios/` stays opt-in
  [`pyproject.toml:83`](../../../pyproject.toml#L83)

**The recursion — testvibe driving testvibe (start here)**

- MCP `run_scenario` spawns pytest on a testvibe scenario; asserts `passed=True` report
  [`test_s4b_mcp.py:46`](../../../scenarios/test_s4b_mcp.py#L46)

- Infra-vs-product split, BOTH branches (exit≠1→infra, exit==1→product); product branch proven load-bearing by live mutation this run
  [`test_s4b_mcp.py:125`](../../../scenarios/test_s4b_mcp.py#L125)

**Anti-no-op keystones (the fable fraud-fixes)**

- `_BreakableModel` proves the fuzz harness catches invariant violations, not just rubber-stamps
  [`test_s7_fuzz.py:105`](../../../scenarios/test_s7_fuzz.py#L105)

- Stale-body refresh distinguishes a working `scaffold.upgrade` from a silent no-op
  [`test_s2_registry_keep.py:55`](../../../scenarios/test_s2_registry_keep.py#L55)

**Real-usage paths, one per surface**

- `scrub_env` drops prefixed keys; `RunReport` redacts `ghp_`/`AKIA` tokens in JSON
  [`test_s0_gate.py:23`](../../../scenarios/test_s0_gate.py#L23)

- `compare_to_baseline` boundary pinned (threshold=within, threshold+ε=regression); sparse-file portability guard
  [`test_s5_perf.py:30`](../../../scenarios/test_s5_perf.py#L30)

- `load_corpus`/`promote_corpus` round-trip on a tmp-only `known-failures.yaml` (no collection collision)
  [`test_s7_fuzz.py:154`](../../../scenarios/test_s7_fuzz.py#L154)

**Peripherals**

- Isolation guard + shared `_unwrap`; the session fixture is the real backstop against a leaked corpus file
  [`conftest.py:1`](../../../scenarios/conftest.py#L1)
