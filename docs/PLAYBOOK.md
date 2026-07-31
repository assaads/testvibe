# testvibe PLAYBOOK — adopt testvibe on any tool (one page)

testvibe is scenario-driven, agent-driven real-usage testing. Your tool's
real-world usage becomes ordinary pytest tests tagged `@scenario`; testvibe's
pytest plugin adds the **surface checks** (invariants, perf, advisories, the
captured-failure auto-pin) around each one. A coding agent (Claude Code / Codex)
is the AI — testvibe ships **no bundled LLM**.

**Adoption is a fill-in-the-blanks contract, not a redesign.** Four steps:

```
fill the six blanks  →  testvibe init  →  write @scenario tests  →  run the gate (or: testvibe autopilot)
```

---

## Step 1 — Fill the six blanks (write `testvibe.yaml`)

To onboard a tool, fill in six blanks; the eight surfaces fall out mechanically.

| # | Blank | Feeds surface(s) |
|---|---|---|
| ① | **Real boundaries** — external systems the tool touches | S3 canary targets |
| ② | **Core invariant** — the property that must hold | S2 property tests |
| ③ | **"It works" observable** — the end-to-end success signal | S3 / S4 verify; Run Report "What worked" |
| ④ | **Real data source** — a sanitized copy of real input | S4 dogfood data |
| ⑤ | **Perf dimensions** — CPU / latency / mem that matter + a baseline | S5 benchmarks + S4 telemetry |
| ⑥ | **Existing test assets** — hermetic infra already present | "extend, don't rebuild" |

Write them into a `testvibe.yaml` contract at the tool's repo root.

## Step 2 — `testvibe init`

```
testvibe init testvibe.yaml --into tests/
```

Scaffolds the scenario skeleton: `test_s1_boundary.py`, `test_s2_property.py`,
`known-failures.yaml`, `conftest.py` — each with commented guidance and a labeled
`# testvibe:keep` block where your tool-specific scenarios go. Later,
`testvibe upgrade` refreshes the scaffolding while preserving every `# testvibe:keep`
region; never drop user code.

## Step 3 — Write `@scenario` tests

Scenarios are native pytest tests. The decorator is the only testvibe API surface:

```python
from testvibe import scenario, invariant

@scenario("push_pull_roundtrip")              # kind defaults to "hermetic" → runs in the gate
def test_push_pull_roundtrip(env):
    ...

@scenario("live_github_create", kind="canary")   # skipped locally; run on schedule / via MCP
def test_live_github_create(env):
    ...

@invariant("failed_op_not_synced")               # asserted alongside scenarios by the plugin
def check_failed_op_not_synced(state):
    ...
```

- `kind ∈ {hermetic, canary, dogfood}` — hermetic runs in the gate; canary /
  dogfood are skipped locally and run via the scheduler / MCP.
- Capture an invariant once with `@invariant(name)`; the plugin asserts it.

## Step 4 — Run the gate, or let the agent drive

**The gate** (CI / local): runs the hermetic subset only — it **excludes live and
dogfood** marks:

```
pytest -m "testvibe_scenario"      # hermetic scenarios + pinned xfail quarantine
```

A green gate = every hermetic scenario passes and every captured failure is
either fixed or pinned. Captured failures live in `known-failures.yaml`
(`status: open | pinned | fixed`); promotion (`testvibe corpus promote`) is the
only path from `pinned` → `fixed`, and only after a deterministic green re-run.

**Autopilot** (the agent runs the full loop):

```
testvibe autopilot        # or: ask Claude Code / Codex to "run testvibe on this tool"
```

The agent discovers the tool, drafts scenarios from traces + coverage gaps, runs
every surface via the MCP tools (`run_scenario`, `get_run_report`,
`list_coverage_gaps`, `list_advisories`), writes/fixes test code and seeds the
corpus (`add_corpus_entry`), and promotes fixes (`promote_corpus`). See
[`skills/testvibe-autopilot/SKILL.md`](../skills/testvibe-autopilot/SKILL.md).

> **Operating principle — AI proposes, deterministic disposes.** The agent writes
> test code freely; changes to the tool's **own source** (`src/**`) require a
> human review gate. The agent never claims fixed without a green re-run.

---

## Per-surface how-to

| Surface | What it is | How you exercise it |
|---|---|---|
| **S0** CI gate | Hermetic subset, redacts tool-specific env that causes false failures | `pytest -m "testvibe_scenario"` on PR + push; scrub env (e.g. `env -u <TOOL>_VAR`). |
| **S1** Hermetic adversarial | Realistic failure-shape fixtures (symlink trees, unicode paths, broken perms, dirty tree) | Add hermetic `@scenario` tests that drive the real engine against hostile inputs. |
| **S2** Property | The core invariant (blank ②) as a Hypothesis test | `@invariant(name)` + a property test asserting it; failure-path state invariants belong here. |
| **S3** Canary | Exercises the **real boundaries** (blank ①) on schedule | `@scenario(..., kind="canary")`; nightly cron; quarantined; uses a scratch resource + scoped credential. |
| **S4** Dogfood | Runs the tool end-to-end on **real data** (blank ④), captures telemetry + diff | `@scenario(..., kind="dogfood")` (or a `dogfood` subcommand) on a real host; asserts the observable (blank ③). |
| **S5** Perf | Benchmarks the perf dimensions (blank ⑤) vs a baseline | `testvibe bench` shapes; regression-asserted in S4 telemetry. |
| **S6** Advisory | Improvement signals (slow-but-passing, smells, coverage gaps) — **data only** | `testvibe` computes them; the agent (via autopilot) turns each into a new scenario. |
| **S7** Discovery & capture | Fuzzer + captured-failure corpus → quarantine → promote auto-pin | Fuzz with the `TestvibeStateMachine` base; every captured failure → `known-failures.yaml` → pinned `xfail` → promoted when fixed. |

A tool is **real-usage-ready** when all eight surfaces exist and the
canary-of-the-canary self-test (a deliberately-broken fixture the canary *must*
catch) passes.

## Failure taxonomy (don't skip this)

Every failure in S3 / S4 / S6 is tagged **infrastructure** (network, rate-limit,
missing secret, env) or **product** (wrong result). A rate-limit must not
register as a product bug, and a real bug must not hide behind an infra skip.
Every captured log / diff / report passes through `detect-secrets` redaction
before storage or alerting — no secret value ever reaches a report.
