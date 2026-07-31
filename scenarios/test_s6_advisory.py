"""S6 self-dogfood scenario: advisory analyzer (DATA ONLY — no LLM, no network).

``advisory.analyze`` returns three non-blocking advisory kinds from run data:

* ``slow_but_passing`` — an op whose p90 exceeds the baseline yet still passed.
* ``smell``            — a transcript line matching deprecation/TODO/FIXME/HACK.
* ``coverage_gap``     — a path touched by traces but absent from fixtures.

The analyzer is pure: it makes zero LLM/network calls. These tests drive it with
synthetic data and assert the exact kinds returned.
"""

from __future__ import annotations

from testvibe import scenario
from testvibe.advisory import analyze


@scenario("s6_advisory_analyze", kind="hermetic", surfaces=("advisory",))
def test_s6_advisory_analyze() -> None:
    """analyze returns the expected advisory kinds for synthetic run data."""
    # --- slow_but_passing: passed op whose p90 exceeds the baseline ---
    ops = [{"name": "op_slow", "p90_ms": 250, "passed": True}]
    rows = analyze(
        report=ops,
        baseline=200,
        fixture_paths=["src/a.py"],
        touched_paths=["src/a.py"],
        transcript="",
    )
    kinds = {r.kind for r in rows}
    assert "slow_but_passing" in kinds, (
        f"expected slow_but_passing for a 250ms op over a 200ms baseline, got {kinds}"
    )
    # A passed-but-slow op is advisory, never a failure: the row is non-blocking.
    slow = next(r for r in rows if r.kind == "slow_but_passing")
    assert "op_slow" in slow.detail and "250" in slow.detail

    # --- smell: a deprecation/TODO line in the transcript ---
    rows = analyze(
        report=[],
        baseline=None,
        fixture_paths=[],
        touched_paths=[],
        transcript="WARNING: DeprecationWarning: foo is deprecated\nplain line\n",
    )
    smells = [r for r in rows if r.kind == "smell"]
    assert len(smells) == 1, f"expected 1 smell row, got {len(smells)}: {smells}"
    assert "deprecat" in smells[0].message.lower()
    # A plain line with no smell token is NOT flagged.
    assert all("plain line" not in r.message for r in smells)

    # --- coverage_gap: a touched path absent from fixtures ---
    rows = analyze(
        report=[],
        baseline=None,
        fixture_paths=["src/covered.py"],
        touched_paths=["src/covered.py", "src/uncovered.py"],
        transcript="",
    )
    gaps = [r for r in rows if r.kind == "coverage_gap"]
    assert len(gaps) == 1, f"expected 1 coverage_gap, got {len(gaps)}: {gaps}"
    assert "src/uncovered.py" in gaps[0].detail
    # A touched path that IS in fixtures is NOT a gap.
    assert all("src/covered.py" not in r.detail for r in gaps)


def test_s6_advisory_no_rows_for_clean_data() -> None:
    """Clean run data yields zero advisories (no false positives)."""
    rows = analyze(
        report=[{"name": "op_ok", "p90_ms": 50, "passed": True}],
        baseline=200,
        fixture_paths=["src/a.py"],
        touched_paths=["src/a.py"],
        transcript="nothing smelly here\n",
    )
    assert rows == [], f"clean data should yield no advisories, got {rows}"


def test_s6_advisory_slow_guard_edges() -> None:
    """The slow_but_passing guard only fires when passed AND p90 is numeric.

    Pins the real analyzer guards in ``advisory.analyze``:
    ``if passed and baseline is not None and p90 is not None and p90 > baseline``.
    A ``p90_ms=None`` op must NOT be flagged (the ``p90 is not None`` guard),
    and a slow op that FAILED must NOT be classified slow_but_passing (the
    ``passed`` guard) — even though its p90 exceeds the baseline.
    """
    # (a) A None-p90 op yields no slow_but_passing advisory.
    rows = analyze(
        report=[{"name": "op_missing_p90", "p90_ms": None, "passed": True}],
        baseline=200,
        fixture_paths=["src/a.py"],
        touched_paths=["src/a.py"],
        transcript="",
    )
    assert all(r.kind != "slow_but_passing" for r in rows), (
        f"a None-p90 op must not be flagged slow_but_passing, got: {rows}"
    )

    # (b) A slow-but-FAILING op is NOT classified slow_but_passing.
    rows = analyze(
        report=[{"name": "op_slow_fail", "p90_ms": 250, "passed": False}],
        baseline=200,
        fixture_paths=["src/a.py"],
        touched_paths=["src/a.py"],
        transcript="",
    )
    assert all(r.kind != "slow_but_passing" for r in rows), (
        f"a slow-but-failing op must not be slow_but_passing (it already failed), got: {rows}"
    )
