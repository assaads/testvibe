# testvibe

> **Status: v0.1 (dev) — package IMPLEMENTED (Phases A/B/C).** The deterministic
> engine, pytest plugin, MCP server, autopilot skill, and `init`/`upgrade` CLI are
> built and pass the gate (`ruff` + `mypy` + 95 tests + `uv build`). **Phase D —
> proving it on syncestra across all 8 surfaces + live provisioning — is deferred**
> (needs the syncestra repo + infra); see
> [`docs/superpowers/plans/2026-07-30-testvibe.md`](docs/superpowers/plans/2026-07-30-testvibe.md).

**Scenario-driven, agent-driven real-usage testing for any tool that integrates
with external systems.** testvibe closes the gap where a tool's unit tests pass
but it breaks in real day-to-day usage — by exercising the tool the way it's
actually used, watching it run, and pinning every failure permanently.

It is **not** a controlling harness, and it ships **no bundled LLM**. It is three
light things:

- **A pytest plugin** — you write your real-world usage as ordinary pytest tests
  tagged `@scenario`. The plugin (auto-activated on `pip install testvibe`)
  augments each scenario with the *surface checks*: invariants, performance
  telemetry, improvement advisories, and the captured-failure auto-pin.
- **An MCP server** — exposes the deterministic engine to a coding agent
  (Claude Code / Codex), which **is** the AI: it reads reports, proposes new
  scenarios, distills repros, and writes the test code.
- **An autopilot skill** — composes the granular tools into one autonomous loop
  the agent runs end-to-end. The granular tools stay individually usable.

## The model — scenarios × surfaces

- **Scenarios** are the *content*: each tool declares its real-world scenarios
  (freeform, tool-specific). A scenario is a native pytest test.
- **Surfaces** are the *checks* applied to every scenario: `S0` CI gate, `S1`
  hermetic adversarial, `S2` property, `S3` real-boundary canary, `S4` continuous
  dogfood, `S5` perf benchmarks, `S6` advisory (improvement detection), `S7`
  discovery & capture (fuzzer + captured-failure corpus + quarantine→promote
  auto-pin).
- **`testvibe init`** scaffolds the scenario skeleton; **`testvibe upgrade`**
  refreshes it while preserving your hand-written code inside `# testvibe:keep`
  regions.

## Operating principle

**AI proposes, deterministic disposes.** The agent (you, via Claude Code/Codex)
drafts scenarios and writes tests; the surface checks are deterministic and
decide pass/fail; pinning goes through `xfail(strict)`. The autopilot may freely
write/fix **test** code, but changes to a tool's **own source** require a human
review gate.

## Repo contents

**Package (`src/testvibe/`):**

| Module | Responsibility |
|---|---|
| `scenario.py` | `@scenario(name, kind=)` / `@invariant(name)` decorators + registries. |
| `plugin.py` | pytest plugin (`pytest11` entry point): `env` fixture, perf/advisory markers, quarantine auto-pin from `known-failures.yaml`. |
| `report.py` | `RunReport` (JSON + markdown, infra-vs-product tagging, `detect-secrets` redaction). |
| `corpus.py` | `known-failures.yaml` read/write + quarantine→promote. |
| `fuzz.py` | `TestvibeStateMachine` (Hypothesis) base for S7. |
| `bench.py` | `scale_tree`, `sparse_file`, `compare_to_baseline` (S5). |
| `gate.py` + `.github/actions/testvibe-gate/action.yml` | `scrub_env(prefix)`, composite action (S0). |
| `canary.py` | S3 helpers: rate-limit backoff, scratch-resource lifecycle. |
| `dogfood.py` | S4 helpers: CPU/RSS/latency telemetry + diff + RC5-spin assertion. |
| `advisory.py` | S6 analyzer: slow-but-passing, smells, coverage gaps (data only — no LLM). |
| `mcp.py` | **MCP server** exposing the engine to a coding agent (6 tools). |
| `scaffold.py` | `init` (skeleton) + `upgrade` (re-merge, respects `# testvibe:keep`). |
| `cli.py` | `testvibe` CLI: `init`, `upgrade`, … |

**Adoption / instructions:** `skills/testvibe-autopilot/SKILL.md`, [`docs/PLAYBOOK.md`](docs/PLAYBOOK.md).

**Design docs:** [`…/2026-07-29-real-usage-testing-design.md`](docs/superpowers/specs/2026-07-29-real-usage-testing-design.md), [`…/2026-07-30-testvibe.md`](docs/superpowers/plans/2026-07-30-testvibe.md).

## Adoption

The package builds and tests pass. Install from source (not yet on PyPI):

```bash
uv sync --all-extras          # dev + mcp + fuzz extras
uv run pytest -q              # 95 tests
uv build                      # sdist + wheel
```

A tool adopts testvibe by writing a `testvibe.yaml` contract → `testvibe init`
→ filling `@scenario` tests → running the gate, or invoking the **autopilot**
skill (`skills/testvibe-autopilot/SKILL.md`). See [`docs/PLAYBOOK.md`](docs/PLAYBOOK.md)
for the full recipe.

**Reference instantiation:** [syncestra](https://github.com/assaads/syncestra)
(the tool whose real RC2/RC4/RC5 production incidents shaped this design).
**Planned adopters:** LeaFS, tokiwoki.
