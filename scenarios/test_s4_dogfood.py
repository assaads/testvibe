"""S4 self-dogfood scenario: dogfood skip-mark + RC5-spin regression detector.

Mirrors S3's split: ``@scenario(kind="dogfood")`` is itself the skip-marked
dogfood (collected but not run locally), and ``assert_no_regression`` is
exercised in always-run plain tests against synthetic CPU/RSS samples so the
RC5-spin predicate is provably correct without depending on wall-clock timing
or a real host.
"""

from __future__ import annotations

import pytest

from testvibe import scenario
from testvibe.dogfood import assert_no_regression
from testvibe.scenario import SCENARIOS


@scenario("s4_dogfood_skip_and_telemetry", kind="dogfood")
def test_s4_dogfood_skip_and_telemetry() -> None:
    """Dogfood body: collected+skipped locally. Only skip-semantics matter."""
    raise AssertionError("dogfood body ran locally — skip-mark regressed")


def test_s4_dogfood_is_skip_marked() -> None:
    """The registered dogfood scenario is collected but skip-marked (skip-semantics)."""
    fn = SCENARIOS["s4_dogfood_skip_and_telemetry"]["fn"]
    assert fn.__testvibe__["kind"] == "dogfood"
    has_skip_mark = any(
        getattr(mark, "name", None) == "skip"
        for mark in getattr(fn, "pytestmark", [])
    )
    assert has_skip_mark, "dogfood scenario was not skip-marked"


def test_s4_assert_no_regression_flags_rc5_spin() -> None:
    """RC5 spin signature — sustained high CPU + flat RSS — is flagged (raises)."""
    # 5 samples: CPU pinned at 95%, RSS flat at 100MB across all of them.
    spin = [(95.0, 100.0)] * 5
    with pytest.raises(AssertionError, match="RC5 spin signature"):
        assert_no_regression(spin, cpu_pct=90.0, flat_rss_eps_mb=5.0)


def test_s4_assert_no_regression_clears_when_rss_rising() -> None:
    """High CPU but RSS rising (work progressing) is NOT a regression."""
    # Same high CPU, but RSS grows sample-over-sample: forward progress.
    rising = [(95.0, 100.0), (95.0, 130.0), (95.0, 160.0)]
    # Must NOT raise.
    assert_no_regression(rising, cpu_pct=90.0, flat_rss_eps_mb=5.0)


def test_s4_assert_no_regression_clears_when_cpu_not_sustained() -> None:
    """Flat RSS but CPU below threshold is NOT a regression."""
    low_cpu = [(40.0, 100.0)] * 5
    assert_no_regression(low_cpu, cpu_pct=90.0, flat_rss_eps_mb=5.0)


def test_s4_assert_no_regression_clears_on_short_input() -> None:
    """Fewer than two samples cannot demonstrate a sustained spin — clears."""
    assert_no_regression([], cpu_pct=90.0, flat_rss_eps_mb=5.0)
    assert_no_regression([(95.0, 100.0)], cpu_pct=90.0, flat_rss_eps_mb=5.0)
