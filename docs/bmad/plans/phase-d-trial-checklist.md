# Phase D trial checklist — closing the doc-vs-reality gap

> **Status:** supplements [`docs/superpowers/plans/2026-07-30-testvibe.md`](../superpowers/plans/2026-07-30-testvibe.md) (Phase D).
> The plan aspires to "Phase D — NOTHING deferred" (full syncestra reference +
> provisioning). The README concedes Phase D is deferred (needs the syncestra
> repo + infra). **This file is the bridge:** a concrete, ordered "first real
> external tool" trial that converts the self-dogfood proof (commit `bca79be`)
> into "works on tools that aren't testvibe." It also records three gaps the
> original plan did not foresee.

## Why this exists

The plan's Phase D proves readiness on **syncestra** (an external tool). On
`2026-07-31` we shipped a **self-dogfood** suite (`scenarios/`, commit `bca79be`)
— testvibe testing itself across all 8 surfaces + an S4b MCP round-trip,
mutation-verified (fraud_verdict: VERIFIED), running in CI (commit `439d948`).

That is **real, first end-to-end evidence** — but it is the *easiest* case
(the tool and the test target share a brain). A different tool is a genuinely
harder test. So: ready to *try* on a real second tool — yes. Ready to claim
"production-proven on arbitrary tools" — **not yet.** This checklist is that
trial.

## The trial — pick ONE real external tool, run this in order

Mirrors the PLAYBOOK (`docs/PLAYBOOK.md`) + Phase D Tasks D1–D5, scoped to a
single tool so a failure surfaces fast.

- [ ] **1. Choose the tool.** One tool you own that integrates with an external
      system (syncestra is the plan's reference; LeaFS/tokiwoki are named
      follow-ons). Needs its real repo + any live infra/credentials.
- [ ] **2. Write `testvibe.yaml`** — the six-blank contract (what the tool is,
      its real-world scenarios, its external boundaries). See PLAYBOOK Step 1.
- [ ] **3. `testvibe init <contract> --into tests/testvibe/`** — scaffolds the
      four surfaces (`init` + `upgrade` are the two fully-working CLI paths).
- [ ] **4. Seed scenarios by hand first** (S0/S1/S2) — a few `@scenario` tests
      for the tool's hermetic core. This proves the plugin activates and
      collects on a *foreign* repo, not just testvibe's own.
- [ ] **5. Let the agent drive** — in Claude Code, "run testvibe on this tool."
      The autopilot skill drafts scenarios automatically (it is the AI;
      testvibe makes no LLM calls) and STOPS at two gates: any `src/**` edit,
      and final delivery. Watch for the stop-conditions firing correctly on a
      tool you did not write.
- [ ] **6. Seed a real captured failure → promote** (S7). Take one real incident
      on the tool, write a repro, `add_corpus_entry`, confirm `xfail(strict)`
      xpass → `promote_corpus` → permanent hard test. This proves the
      discover→capture→promote loop on a real bug, the plan's Task D5 outcome.
- [ ] **7. Wire the gate** in that tool's CI: `pytest -m "not live and not
      dogfood"` (hermetic) + a `pytest tests/testvibe/` step. Green = every
      hermetic scenario passes and every captured failure is fixed-or-pinned.
- [ ] **8. Record what broke.** Anything that failed on the foreign tool but
      passed in self-dogfood is the v0.2 punch list. This file's "gaps" section
      is the seed of that list.

**Definition of "trial passed":** steps 1–7 green on a tool that is NOT
testvibe, with at least one real incident promoted to a hard test (step 6).

## Gaps the original plan did NOT foresee

Three things surfaced by actually running the work (`2026-07-31`) that the plan
does not capture:

### G1 — CLI stub gap (plan vs. code drift)
The plan's File Structure lists `cli.py` with `run`, `corpus {add,promote}`,
`dogfood`, `canary`, `autopilot`. The **actual code** (`src/testvibe/cli.py`)
has those as exit-2 `_not_implemented` stubs. Only `init` and `upgrade` work
from the CLI. **Implication:** the agent-driven path (MCP + autopilot skill)
is the working one today; the standalone CLI is not a full replacement. The
plan's DoD implies these exist — they don't. Resolve by either implementing
them or correcting the plan's File Structure to mark them planned-but-stubbed.

### G2 — Self-dogfood is a new proof point the plan never specified
The plan proves readiness on syncestra. The `scenarios/` suite (commit
`bca79be`) — testvibe testing itself — is **complementary evidence the plan
did not ask for.** It is the cheaper, first proof; Phase D (above) is the
harder, external proof. Both belong in the definition of "proven."

### G3 — Two real bugs surfaced by running (security + gate)
- **`mypy` with no target** in `.github/actions/testvibe-gate/action.yml` —
  bare `run: mypy` errors; fixed to `mypy src` in commit `439d948`. (Pre-existing
  latent CI bug; also recorded in [`deferred-work.md`](../deferred-work.md).)
- **Embedded GitHub PAT in `origin` remote URL** — `git remote -v` leaks a valid
  `ghp_…` token. Rotate and move the credential to a credential helper / env /
  SSH remote. Security item, not a code bug. (Tracked in project memory:
  `testvibe-remote-embedded-pat`.)

Neither is in the plan; both came from executing, not designing.

## Relationship to the plan

This file **does not supersede** `2026-07-30-testvibe.md`. It narrows Phase D
into a single-tool trial a human can run in one session, and records the three
gaps above. When the trial (or the gaps) are resolved, fold the outcomes back
into the plan's Phase D / DoD and retire this checklist.
