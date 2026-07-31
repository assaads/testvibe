# Real-Usage Testing Methodology — "Testvibe Surfaces"

**Date:** 2026-07-29
**Status:** Design (brainstorming output, pending implementation plan)
**Scope:** Cross-tool methodology, instantiated first on **syncestra**, then liftable to **LeaFS** and **tokiwoki**, and to any future tool.
**Origin:** Brainstorming session — "tools pass their internal tests but break in real day-to-day usage; how do we test them so thoroughly that real-usage bugs/perf issues are caught before I hit them?"

---

## 1. Problem & diagnosis

Across syncestra, LeaFS, and tokiwoki, the recurring pattern is: **unit/integration tests pass, but real usage surfaces errors nobody anticipated.** Four failure modes were confirmed as actively biting:

1. **Boundary / integration** — the real GitHub / git / filesystem / MCP behaved differently than the test assumed.
2. **State / convergence logic** — the core algorithm misbehaves on edge cases (last-write-wins across two machines, conflicts, clock skew, concurrent writes).
3. **Environment / machine-specific** — works on the laptop, breaks on the VPS / cloudcli (env vars, perms, paths, Python version, missing system deps).
4. **Performance / scale** — fine on small inputs, slow / OOM / timeouts once the real input is large.

**Root-cause diagnosis (verified against syncestra):** the problem is *not* test count. syncestra already has a strong pyramid (`unit/`, `integration/` with ~25 suites, `e2e/` with 6 user-journey suites), drives **real git** via a `make_bare_remote` bare-repo fixture (zero `mocker` in `tests/integration/`), and even has a **real-GitHub live test** (`tests/e2e/test_github_live_auth.py`, gated on `SYNCESTRA_E2E_TOKEN`/`SYNCESTRA_E2E_REMOTE`).

The real gaps are **gating, automation, fidelity at the boundaries, and the absence of an improvement channel**:

- **No CI test gate.** The only workflow (`publish.yml`) runs on push to `main`, computes a version, builds, and publishes to PyPI. It **never runs `pytest`**. The entire suite — including the live seed — runs only when a human remembers. A broken commit ships to PyPI unchecked.
- **The live boundary test is manual-only.** The real-GitHub seed exists but is never automated/scheduled, so "real boundary" testing happens ~never.
- **No property tests for the core invariant.** last-write-wins convergence has no Hypothesis suite proving idempotence / commutativity / round-trip, so logic bugs slip through.
- **No continuous dogfood.** Nothing runs the tool on real input, in the real environment, with telemetry, on a schedule.
- **No perf gate, no CPU/resource telemetry.** Scale and resource issues are unmeasured.
- **No improvement-detection channel.** The harness only says pass/fail; it never surfaces "this works but could be better."

**Headline:** the missing ~80% is *gating + automation + continuous real-usage fidelity + an advisory channel* — not new unit tests. The design **extends existing machinery** rather than rebuilding it.

---

## 2. Goals & non-goals

**Goals**
- A reusable methodology that makes any tool "real-usage-ready": real boundaries driven, core invariant proven, real env/data exercised continuously, perf watched, and improvement opportunities surfaced.
- A pre-merge gate so no tool ships with zero tests run (closes the syncestra bleeding wound first).
- A first-class **Run Report** that says what happened (not just pass/fail) and a **"could be better"** advisory section.
- Onboarding a new tool is a fill-in-the-blanks contract, not a redesign.

**Non-goals (YAGNI)**
- A fake/mock GitHub API server in the hermetic layer — the live canary already drives the real API; a fake only tests our model of reality. (Revisit only if canary secrets become untenable.)
- A production observability stack. Start with JSON reports + CI artifacts + simple alerts.
- Generalizing to tools outside the user's own fleet in this phase.

---

## 3. The methodology — eight Testvibe Surfaces

A tool is "real-usage-ready" when these eight surfaces exist, each at the right realism/cost point. The surfaces describe **classes of risk** that every tool has; they are tool-agnostic. Per tool, only two blanks change (see §5). **S7 makes the methodology *live*:** it discovers failure modes no one enumerated and permanently pins them.

| Surface | What it proves | Realism | Runs when | Blocks merge? |
|---|---|---|---|---|
| **S0 — CI test gate** | the suite you already have actually runs | n/a | every PR + push | ✅ yes |
| **S1 — Hermetic core (stateful fakes)** | boundary behavior at the seams | real git/FS, no network | every PR | ✅ yes |
| **S2 — Property tests** | the core invariant holds mathematically | model | every PR | ✅ yes |
| **S3 — Real-boundary canary** | real external systems behave as assumed | **real** external systems | nightly + on tag | ⛔ quarantined |
| **S4 — Continuous dogfood** | the tool works on *your real data/env* daily | **real everything** | cron, real machine | ⛔ alert-only |
| **S5 — Perf benchmarks** | no scale/resource regression | scale fixtures | every PR | ✅ threshold-gated |
| **S6 — Advisory (improvement detection)** | latent fragility + improvement opportunities surfaced | derived from S3/S4/S5 | with each run | ⛔ non-blocking |
| **S7 — Discovery & Capture** | unknown failure modes found + pinned as regression tests | fuzzer + captured-failure corpus | every PR (bounded fuzz) + on each capture | ✅ once promoted |

**Why S3 and S4 are quarantined:** they drive real external systems / real environments, so network flakiness, rate limits, and env noise live there. They must never block a merge (false blockers destroy trust in the gate). Instead they **alert** and feed the Run Report.

**Why S3 ≠ S4 (a deliberate split):**
- **S3** runs on a **clean CI matrix** (e.g. GitHub Actions, Python 3.11/12/13) against a dedicated scratch repo. It catches *cross-version* and *real-API* issues. Clean by design.
- **S4** runs on the **actual target machine** (cloudcli/VPS) against a sanitized copy of the **real** data. It is the only surface that catches *environment-specific* and *real-scale* issues, because a clean CI runner is not your real environment. This split directly serves failure modes #3 and #4.

### Surface details (tool-agnostic)

**S0 — CI test gate.** A workflow that runs the *hermetic* subset (unit + integration + e2e-journeys + property + perf), lint, type-check, on a version matrix, with any tool-specific env vars that cause false failures **scrubbed** (syncestra: `SYNCESTRA_*`). The live/quarantined surfaces are excluded from this gate.

**S1 — Hermetic core (stateful, adversarial).** Replace mocks with **stateful fakes** and exercise the **failure surface**, not just the happy path: real local git/FS where possible, plus adversarial fixtures (symlinks, unicode/space paths, broken perms, large trees, large binaries, dirty working trees, protected-branch stand-ins). The goal is "the boundary fails the way the real one fails" — hermetically.

**S2 — Property tests.** State the tool's **core invariant** as a property and test it with a property-based tester (Hypothesis). This is the logic-bug catcher that unit tests cannot be (unit tests check examples; property tests check the *space*).

**S3 — Real-boundary canary.** Drive the **actual external systems** the tool depends on, against disposable scratch resources, on a schedule (nightly + on release tag), gated behind an env flag, **quarantined** from the merge gate, rate-limit-aware (retry with backoff). Data source: a **sanitized copy of real input**.

**S4 — Continuous dogfood.** On a cron on the **real target machine**: mirror a sanitized copy of real input → run the full real cycle end-to-end → capture telemetry (exit code per step, wall-clock, **peak RSS, CPU** per step, and a "success diff" that must be empty) → emit a Run Report → alert on regression. Operates on a **copy**; fully idempotent and reversible; never mutates the live data.

**S5 — Perf benchmarks.** Benchmark suites on generated scale fixtures (small / medium / large), regression-gated against a **committed baseline** (bumped deliberately). Resource-aware: not just wall-clock but **CPU and memory** under load.

**S6 — Advisory / improvement detection.** Every run classifies signals into three buckets; the Run Report always has a **"Could be better"** section:
- *Failures* — product bugs (blocking in S1/S2/S5; alerting in S3/S4).
- *Perf regressions* — beyond threshold (blocking/alerting).
- *Advisories* — non-blocking improvement signals, sourced from:
  - **Slow-but-passing** ops (under the fail threshold but trending into the top quartile vs baseline).
  - **Smells the tool emits** during the run — deprecation notices, fallback paths taken, retries triggered. Each is a latent-fragility signal.
  - **Coverage gaps** — real shapes observed in the dogfood data that no hermetic test exercises (auto-derived by diffing the run's touched paths against the test-fixture corpus).
  - **LLM fragility review (optional, pluggable)** — feed the run transcript + diffs to a model with a "what's fragile / what could be improved" prompt → structured advisories. A missing key degrades to *skipped + logged*, never blocks (resilient-review pattern).

**S7 — Discovery & Capture (the self-growing engine).** The methodology must find failure modes no one enumerated, and lock them in once found. Three parts:
- **Fuzzer** — a stateful/rule-based property test (Hypothesis `RuleBasedStateMachine`) that generates random sequences of the tool's operations over randomly-generated tree states and asserts the **invariant catalog** (S2) holds after every step. This discovers unanticipated interactions (push-after-failed-pull, concurrent-write-during-restore, diverge-then-watch) without a human dreaming them up. Bounded in CI (small example budget), unbounded in nightly. Per tool, it fuzzes the ops from blank ① against the invariants from blank ②.
- **Captured-failure corpus** — a versioned registry (`tests/corpus/known-failures.yaml` + one repro fixture dir per entry). Every failure surfaced by *any* source — the fuzzer, S4 dogfood, S6 advisory, or a real production incident — is recorded with: a minimal reproducer, the invariant violated, when/by-whom discovered, and fix status (`open` / `pinned` / `fixed`). This is the "canary-of-the-canary" (§6) generalized into a living catalog: **the corpus only ever grows.**
- **Quarantine → promote (auto-pin)** — each `open` corpus entry emits a **quarantined test** (`@pytest.mark.quarantine` = `pytest.xfail(strict=True, reason=...)`). The moment the underlying fix lands, the `xfail` flips to `xpass` → CI fails loudly → an engineer promotes it to a real regression test (drop the `xfail`) and flips the corpus entry to `fixed`. Closed loop: **discover → capture → quarantine-pin → fix → promote.** Quarantined tests never block a merge; promoted ones do. This is what turns a one-off incident into permanent protection.

---

## 4. The Run Report (produced by S3 + S4)

A first-class artifact, not just a pass/fail. Structured JSON + a rendered summary, with sections:

1. **Summary** — what ran, where, pass/fail, duration.
2. **What worked** — the end-to-end success signal observed (this is the tool's ③ "it works" observable). The proof that the tool *actually did its job* on real data.
3. **Failures** — each tagged **infra vs product** (see §6). Infra failures (network, rate-limit, missing secret) never count as product bugs.
4. **Performance** — CPU / peak-RSS / latency per step vs baseline.
5. **Advisory ("could be better")** — the S6 output.

Stored as a CI artifact and written to a `reports/` dir. S4 (dogfood) alerts (e.g. via existing channels) on regression.

---

## 5. Onboarding contract — apply to ANY tool

This is what makes the methodology general. To onboard a tool, fill in six blanks; the eight surfaces then fall out mechanically.

| # | Blank | Feeds surface(s) |
|---|---|---|
| ① | **Real boundaries** — external systems the tool touches | S3 canary targets |
| ② | **Core invariant** — the property that must hold | S2 property tests |
| ③ | **"It works" observable** — the end-to-end success signal | S3/S4 verify; Run Report "What worked" |
| ④ | **Real data source** — a sanitized copy of real input | S4 dogfood data |
| ⑤ | **Perf dimensions** — CPU/latency/mem that matter + a baseline | S5 benchmarks + S4 telemetry |
| ⑥ | **Existing test assets** — hermetic infra already present | "extend, don't rebuild" (the syncestra lesson) |

**Definition: real-usage-ready.** A tool is real-usage-ready when all eight surfaces exist **and** the *canary-of-the-canary* self-test (§6) passes. This lets you grade any tool, present or future.

---

## 6. Cross-cutting concerns

- **Infra-vs-product failure taxonomy.** Every failure in S3/S4/S6 is tagged *infrastructure* (network, rate-limit, missing secret, env) or *product* (wrong result). This is the integration-seam class: a rate-limit must not register as a product bug, and a real bug must not hide behind an infra skip. (Known instance: the `SYNCESTRA_*` env-leak false-failure seam.)
- **Secrets redaction.** Every captured log/diff/report passes through `detect-secrets` + pattern redaction before storage or alerting. (syncestra already depends on `detect-secrets`.) No secret value ever reaches a report.
- **Canary-of-the-canary (self-test).** A **deliberately-broken fixture** that the canary *must* catch. If the canary passes on a known-broken input, the harness itself is broken — defend against the "healthy-but-blind liveness probe" failure (a service answers OK while its real function is dead).
- **Scrub tool-specific env in the gate.** The CI gate runs with any env vars that cause false failures unset (syncestra: `env -u SYNCESTRA_*`), so the gate matches CI reality, not the dev shell.

---

## 7. Syncestra instantiation (concrete)

Filled-in blanks: ① boundaries = {GitHub API, git, filesystem, MCP}; ② invariant = last-write-wins convergence keyed on GitHub commit timestamp; ③ observable = "branches created + services backed up + source/restored byte parity"; ④ data = sanitized copy of `~/.claude`; ⑤ perf = push/pull/status wall-clock + peak-RSS + CPU at 10/1k/10k files; ⑥ assets = `make_bare_remote`, the live `test_github_live_auth.py` seed, the existing integration/e2e suites.

- **S0** — `.github/workflows/test.yml` on PR + push: `uv run pytest tests/unit tests/integration tests/e2e` (hermetic subset, **excluding** the live test), `ruff`, `mypy`, matrix py3.11/3.12/3.13, `env -u SYNCESTRA_*`.
- **S1** — Extend `tests/integration/conftest.py` fixtures: symlink trees, unicode/space paths, broken perms, 10k-file tree, large binary, dirty tree, protected-branch stand-in (local pre-push hook). Real git is already driven — extend the **failure surface**. **No fake GitHub API** (YAGNI — the canary covers the real API).
- **S2** — `tests/property/test_convergence.py` (Hypothesis): idempotence of `pull ∘ push`; commutativity of independent writes; conflict determinism (later timestamp wins); restore round-trip identity modulo excludes. **Plus failure-path state invariants (RC4):** a failed push (`SecretDetectedError`/network) leaves `state ≠ SYNCED`; divergence reaches `CONFLICTED` via `machine.force()` (no SYNCED→CONFLICTED edge); after a successful `init`, the mirror has >0 objects (the "healthy process, dead mirror" guard).
- **S3** — Promote `test_github_live_auth.py` into `tests/canary/` + `.github/workflows/canary.yml` (cron nightly + on tag). Dedicated scratch private repo `syncestra-canary` + scoped secret `SYNCESTRA_CANARY_PAT` (repo-scoped to *only* that repo, or a GitHub App). Extend coverage: repo auto-create, status on a dirty remote, conflict resolution, **MCP `serve` round-trip**. Runs on GH Actions (clean matrix). Quarantined.
- **S4** — `syncestra dogfood` subcommand (or `scripts/dogfood.py`) on a cron **on the real cloudcli/VPS**: mirror sanitized `~/.claude` → `init → push → pull (fresh clone) → status → restore` against the scratch repo → capture exit code / wall-clock / peak-RSS / CPU per step + source-vs-restored diff (must be empty) → Run Report → alert on regression. Operates on a copy; idempotent.
- **S5** — `tests/perf/` with `pytest-benchmark` on 10/1k/10k-file fixtures; gate: fail if push/pull/status regresses >N% vs committed baseline. **Plus two RC-driven axes:** a **total-bytes** axis (RC2 — a few large files summing toward the size-guard threshold, proving the guard refuses before GiB-scale indexing) and a **resource-over-time behavioral test** (RC5 — a long-running `watch --foreground` loop must stay bounded in CPU+RSS; sustained-high-CPU-with-flat-RSS fails).
- **S6** — Advisory channel on every S3/S4 run: slow-but-passing ops, emitted smells (deprecation/fallback/retry), coverage gaps (real paths vs fixture corpus), optional LLM fragility review.
- **S7** — `tests/property/test_fuzz_ops.py` (Hypothesis `RuleBasedStateMachine`) fuzzing `init`/`push`/`pull`/`restore`/concurrent-write sequences against the S2 invariant catalog; `tests/corpus/known-failures.yaml` capturing every discovered/incidental failure with a repro + status; each `open` entry emits a `@pytest.mark.quarantine` (`xfail(strict=True)`) test that auto-promotes (fails CI on `xpass`) when its fix lands. A pulled-forward **watch-loop dogfood slice** (Part 1) feeds RC5-class shapes into the corpus before Part 2's full dogfood exists.

---

## 8. Cross-tool instantiations

**tokiwoki** (filled blanks): ① boundaries = {MCP servers, transport (stdio/HTTP/SSE), tool registry/discovery}; ② invariant = correct routing + tool discovery + response integrity; ③ observable = **N real MCP servers spun up, bidirectional communication + tool discovery verified**; ④ data = a fixture cluster of real MCP server configs; ⑤ perf = message latency, **CPU under concurrent tool calls**; ⑥ assets = TBD on inspection.
→ S3 canary spins up multiple **real** MCP servers and asserts they communicate; S5 watches latency + CPU under concurrency.

**LeaFS** (filled blanks): ① boundaries = {learnings dir filesystem, the hook that consolidates `pending.yaml` → tag-indexed files}; ② invariant = append-never-drops-entries **and** consolidation is idempotent; ③ observable = **every `pending.yaml` entry lands in the correct tag-indexed file with correct naming, none dropped**; ④ data = a realistic `pending.yaml` + history; ⑤ perf = consolidation time at N entries; ⑥ assets = the existing hooks.
→ S3 canary triggers the real hook consolidation and asserts the observable (directly defends the "47 of 60 entries lost" / duplicate-headers bug); S6 flags naming drift.

---

## 9. Phasing (value lands even if we stop early)

1. **S0** (CI gate) — stops the bleeding immediately; a broken commit can no longer reach PyPI untested.
2. **S1 + S2** (hermetic + property) — the pre-merge behavior gate. **RC-driven hardening folds in here** (the plan's Phase 2): S2 failure-path state invariants (RC4), S5 total-bytes + watch-loop resource-over-time (RC2/RC5), and a pulled-forward watch-loop dogfood slice.
3. **S3** (canary) — real-boundary bug catching.
4. **S4 + S5 + S6 + S7** (dogfood + benchmarks + advisory + discovery) — continuous real-usage fidelity + improvement detection + self-growing regression capture.

Stopping after Phase 2 already yields a real pre-merge behavior gate — a massive upgrade over "PyPI publishes with zero tests run."

---

## 10. Success criteria

- A pre-merge CI gate exists and runs the hermetic + property + perf suites, with tool env scrubbed. (Closes the syncestra wound.)
- The real-boundary canary runs on a schedule against real external systems + a scratch repo, quarantined, emitting a Run Report.
- The continuous dogfood runs on the real machine against sanitized real data, emitting a Run Report with CPU/mem/latency telemetry.
- Every Run Report has a non-empty **Advisory** section sourcing improvement signals (and the canary-of-the-canary self-test passes).
- **A fuzzer (S7) runs on every PR + nightly, and every discovered/incidental failure has a pinned regression test** — quarantined (`xfail`) while open, promoted to a hard test once fixed. The captured-failure corpus only grows; no incident is forgotten.
- The onboarding contract (§5) is sufficient to instantiate the methodology on a new tool without redesigning the surfaces.

---

## 11. Open questions / decisions for review

- **Perf regression threshold (N%) and baseline storage** — pick a starting N (e.g. 15%) and a baseline file location.
- **S4 dogfood channel for alerts** — which existing channel receives regression alerts (the user's notification setup).
- **LLM fragility review in S6** — default on (pluggable) vs off until explicitly enabled; which model/prompt.
- **tokiwoki & LeaFS "existing assets" (blank ⑥)** — confirm by inspecting each repo when we reach those phases.
- **Scratch repo / PAT provisioning** — create `syncestra-canary` + the scoped PAT (or GitHub App) and add as CI secret before S3 lands.
