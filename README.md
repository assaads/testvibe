# testvibe

> **Status: pre-v0.1 — design + implementation plan stage.** No code yet; the
> two docs in `docs/` are the source of truth. Tracking implementation against
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

- [`docs/superpowers/specs/2026-07-29-real-usage-testing-design.md`](docs/superpowers/specs/2026-07-29-real-usage-testing-design.md) — the design (eight surfaces + adoption contract).
- [`docs/superpowers/plans/2026-07-30-testvibe.md`](docs/superpowers/plans/2026-07-30-testvibe.md) — the implementation plan (build this).

## Adoption

Pre-v0.1: follow the plan's Phase A to build the package. Once it exists, a tool
adopts it by `pip install testvibe` → write a `testvibe.yaml` contract →
`testvibe init` → fill `@scenario` tests → run the gate, or invoke the
**autopilot**.

**Reference instantiation:** [syncestra](https://github.com/assaads/syncestra)
(the tool whose real RC2/RC4/RC5 production incidents shaped this design).
**Planned adopters:** LeaFS, tokiwoki.
