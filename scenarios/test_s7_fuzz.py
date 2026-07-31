"""S7 self-dogfood scenario: Hypothesis stateful fuzz + quarantine corpus.

Two S7 behaviors:

1. ``fuzz.TestvibeStateMachine`` (``__test__ = False``) is subclassed with
   ``@rule`` transitions and ``@invariant`` properties; the subclass is run via
   ``hypothesis.stateful.run_state_machine_as_test(Factory, settings=...)``. A
   model whose invariant always holds runs clean; a model whose invariant a rule
   can break is caught (proving the harness is not a no-op — verified in the
   mutation check).
2. The quarantine corpus round-trip: ``corpus.load_corpus`` loads an ``open``
   entry from a ``known-failures.yaml`` kept strictly under ``tmp_path`` (never
   under ``tests/`` or repo root — the plugin collects that filename globally),
   and in-process MCP ``promote_corpus(id)`` flips it to ``status: fixed``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from _helpers import _unwrap
from hypothesis import HealthCheck, settings
from hypothesis.stateful import invariant, rule, run_state_machine_as_test
from hypothesis.strategies import integers

from testvibe import scenario
from testvibe.corpus import load_corpus
from testvibe.fuzz import TestvibeStateMachine

# ---------------------------------------------------------------------------
# S7a: stateful fuzz model that always satisfies its invariant -> runs clean.
# ---------------------------------------------------------------------------


class _AdderModel(TestvibeStateMachine):
    """A trivial model: an accumulator that only ever grows (monotone).

    Its invariant (``value >= last_value``) always holds, so the state-machine
    search runs to completion without finding a violation.
    """

    def __init__(self) -> None:
        super().__init__()
        self.value = 0
        self.last_value = 0

    @rule(n=integers())
    def add(self, n: int) -> None:
        # Only non-negative additions: value is monotone non-decreasing.
        if n < 0:
            return
        self.last_value = self.value
        self.value += n

    @invariant()
    def value_never_decreases(self) -> None:
        assert self.value >= self.last_value, (
            f"regression: value {self.value} < last {self.last_value}"
        )


def test_s7_state_machine_runs_clean() -> None:
    """A well-formed TestvibeStateMachine subclass runs clean via the harness."""
    fuzz_settings = settings(
        max_examples=20,
        stateful_step_count=10,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    # Must not raise: the model's invariant always holds.
    run_state_machine_as_test(_AdderModel, settings=fuzz_settings)


class _BreakableModel(TestvibeStateMachine):
    """A model whose invariant a rule CAN violate.

    Unlike ``_AdderModel`` (which short-circuits on negative input so its
    invariant is structurally unbreakable), this model applies every step
    unconditionally. ``add_negative`` pushes ``value`` below ``last_value``,
    violating ``value_never_decreases``. This is the S7 anti-fraud keystone: it
    proves ``run_state_machine_as_test`` actually searches for and catches
    invariant violations (a no-op harness would let the broken model pass).
    """

    def __init__(self) -> None:
        super().__init__()
        self.value = 0
        self.last_value = 0

    @rule(n=integers())
    def add(self, n: int) -> None:
        # No short-circuit: negative steps are applied and violate the invariant.
        self.last_value = self.value
        self.value += n

    @invariant()
    def value_never_decreases(self) -> None:
        assert self.value >= self.last_value, (
            f"regression: value {self.value} < last {self.last_value}"
        )


def test_s7_state_machine_detects_violation() -> None:
    """The harness CATCHES a model whose invariant a rule can break.

    This is the load-bearing anti-fraud check for S7: ``_AdderModel``'s
    invariant is structurally unbreakable (it short-circuits on negative
    input), so the existing ``test_s7_state_machine_runs_clean`` would pass even
    if ``run_state_machine_as_test`` did nothing. A deliberately-broken model
    (whose ``add`` applies negative steps unconditionally) MUST make the harness
    raise — proving the search detects invariant violations rather than
    silently rubber-stamping the model. A no-op harness would fail this test.
    """
    fuzz_settings = settings(
        max_examples=20,
        stateful_step_count=10,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    with pytest.raises(AssertionError):
        run_state_machine_as_test(_BreakableModel, settings=fuzz_settings)


def test_s7_testvibe_state_machine_is_not_collected() -> None:
    """The base class carries __test__=False so pytest never collects it.

    A regression that drops ``__test__ = False`` would make pytest try (and fail)
    to collect the abstract base as a test class.
    """
    assert TestvibeStateMachine.__test__ is False


# ---------------------------------------------------------------------------
# S7b: quarantine corpus round-trip (load open entry; MCP promote -> fixed).
# ---------------------------------------------------------------------------


def _write_open_corpus(path: Path) -> None:
    """Write a single ``open`` entry to ``path`` (a known-failures.yaml)."""
    path.write_text(
        "- id: bug-7\n"
        "  invariant: 'op_slow never regresses p90'\n"
        '  discovered_at: "2026-07-31"\n'
        "  source: self-dogfood\n"
        "  repro: repro_bug_7.py\n"
        "  status: open\n",
        encoding="utf-8",
    )


@scenario("s7_fuzz_and_quarantine", kind="hermetic", surfaces=("invariant",))
def test_s7_fuzz_and_quarantine(tmp_path: Path) -> None:
    """load_corpus loads an open entry; MCP promote_corpus flips it to fixed.

    The corpus file is kept strictly under ``tmp_path`` so the plugin's global
    ``known-failures.yaml`` collector never sees it.
    """
    # --- load_corpus loads the open entry with all required fields ---
    corpus_path = tmp_path / "known-failures.yaml"
    _write_open_corpus(corpus_path)
    entries = load_corpus(corpus_path)
    assert len(entries) == 1, f"expected 1 open entry, got {len(entries)}"
    assert entries[0].id == "bug-7"
    assert entries[0].status == "open"
    assert entries[0].repro == "repro_bug_7.py"

    # --- in-process MCP: promote_corpus(id) -> status fixed ---
    from testvibe.mcp import build_server

    server = build_server(contract_path=None, corpus_path=corpus_path)

    async def drive() -> object:
        # The in-process tool surface: call_tool returns a fastmcp ToolResult;
        # _unwrap (from _helpers) normalizes the structured-content envelope.
        result = await server.call_tool("promote_corpus", {"id": "bug-7"})
        return _unwrap(result)

    promoted = asyncio.run(drive())
    assert isinstance(promoted, dict), f"promote_corpus must return a mapping, got {type(promoted)}"
    assert promoted["id"] == "bug-7"
    assert promoted["status"] == "fixed", (
        f"promote_corpus must flip status to fixed, got {promoted}"
    )

    # --- a promoted (fixed) entry drops out of load_corpus ---
    reloaded = load_corpus(corpus_path)
    assert reloaded == [], (
        "a fixed entry must no longer be collected by load_corpus, "
        f"got {[e.id for e in reloaded]}"
    )
    # The file itself still exists (promote mutates in place, it does not delete)
    # and is still under tmp_path — never leaked onto a repo-collected path.
    assert corpus_path.exists()
    assert corpus_path.parent == tmp_path
