---
name: testvibe-autopilot
description: Run the full testvibe loop autonomously — discover the tool, draft scenarios, run all surfaces, read reports, write/fix tests, seed the corpus, promote. Use when the user says "testvibe autopilot" or "run testvibe on this tool".
---

# testvibe autopilot

You are the AI intelligence layer for testvibe (testvibe itself is deterministic
and makes NO LLM calls — YOU are the AI). Run the full loop using the testvibe
MCP tools + your own read/write/run tools.

## Loop

1. **Discover** the target tool: Read its README/contract, Grep its ops, inspect
   any real-usage traces. Build a mental model of its external boundaries and
   invariants.
2. **Draft scenarios**: from the tool's behavior + traces + coverage gaps (call
   `list_coverage_gaps`), write `@scenario` tests for the real-world shapes not
   yet covered, into the tool's `tests/testvibe/`.
3. **Run all surfaces**: call `run_scenario` for each (or `pytest -m
   testvibe_scenario`). Read every `get_run_report`.
4. **Act on findings**:
   - **Failure** → distill a minimal reproducer; WRITE a `@scenario` or fix the
     existing test; `add_corpus_entry` with the repro; re-run to confirm.
   - **Coverage gap** (from `list_coverage_gaps`) → write the missing scenario.
   - **Advisory** (from `list_advisories`) → write an improvement test.
5. **Iterate** until the gate is green AND no open advisories (or the token
   budget is spent).
6. **Report**: what you discovered, what failed, what you wrote/fixed/pinned.

## Guardrails (non-negotiable)

- **Test code is autonomous**: you may freely create/edit files under
  `tests/**` and `known-failures.yaml`.
- **Tool source is gated**: you may NOT edit the tool's own source (`src/**`)
  without explicit human approval. Propose the change; do not apply it.
- **Determinism rules**: pinning only via `promote_corpus` after a deterministic
  re-run confirms the fix. Never claim fixed without a green re-run.
- **You are the AI provider**: testvibe makes no LLM calls. All reasoning is yours.

## Engine reference (the tools you compose)

testvibe exposes its deterministic engine as MCP tools. They return **structured
data**; you do the reasoning. (The granular tools stay individually usable — the
autopilot loop just composes them.)

| MCP tool | Returns | Use it to |
|---|---|---|
| `run_scenario(name)` | `run_id` — invokes `pytest -m testvibe_scenario -k <name>` | execute one scenario |
| `get_run_report(run_id)` | the `RunReport` JSON | read what happened (pass/fail, invariant, perf, advisory rows) |
| `list_coverage_gaps()` | `coverage_gap` rows (paths in real traces absent from fixtures) | decide which scenarios are missing |
| `list_advisories(run_id)` | advisory rows (`slow_but_passing`, `smell`, `coverage_gap`) | decide what to improve |
| `add_corpus_entry(id, invariant, repro_path, status="open")` | appends to `known-failures.yaml` | seed the S7 net with a captured failure |
| `promote_corpus(id)` | flips a pinned entry to fixed + drops its `xfail` | retire a corpus entry after a green re-run |

### Scenario + corpus vocabulary

- A scenario is an ordinary pytest test tagged with
  `@scenario(name, kind="hermetic" | "canary" | "dogfood")`.
  - `hermetic` runs in the CI gate (default `pytest` collection).
  - `canary` / `dogfood` are skipped locally and run via the scheduler/MCP.
- An invariant is registered with `@invariant(name)` and asserted alongside
  scenarios by the plugin.
- The captured-failure corpus lives in **`known-failures.yaml`**. Each entry has
  `status: open | pinned | fixed`:
  - `open` — freshly captured, repro known, not yet quarantined.
  - `pinned` — quarantined as an `xfail(strict)` so the gate stays green while
    the underlying bug is unfixed. Promotion is the only exit.
  - `fixed` — a deterministic re-run passed; `promote_corpus` flipped it and
    dropped the `xfail`. The entry stays in the file as history.

### The gate

The CI gate runs the **hermetic** subset only — it **excludes live and dogfood**
marks (`pytest -m "testvibe_scenario"` collects hermetic scenarios; canary and
dogfood kinds are skip-marked in local runs and run on schedule). A green gate
means every hermetic scenario passes and every captured failure is either fixed
or pinned.

## Stop conditions

- **STOP** the moment a fix would require editing `src/**` (the tool's own
  source). Write the failing scenario, `add_corpus_entry` it, and surface the
  proposed source change to the human. Do not apply it.
- **STOP** after the gate is green AND no open advisories remain, or the token
  budget is spent — then deliver the report (loop step 6).
