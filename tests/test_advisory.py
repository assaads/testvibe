"""Tests for testvibe.advisory — slow-but-passing, smells, coverage gaps (S6).

DATA ONLY — no LLM, no network call.
"""

from testvibe.advisory import Advisory, analyze


def _op(name, p90_ms, passed):
    return {"name": name, "p90_ms": p90_ms, "passed": passed}


def test_analyze_yields_three_kinds_for_one_of_each():
    """Given a slow-but-passing op, a deprecation smell line, and a path
    touched by dogfood but absent from fixtures, analyze returns 3 advisories.
    """
    report = [
        _op("push", p90_ms=1500, passed=True),  # slow but passed
        _op("pull", p90_ms=100, passed=True),  # fine
    ]
    baseline = 1000  # ms
    fixture_paths = ["tests/test_push.py", "tests/test_pull.py"]
    touched_paths = ["tests/test_push.py", "src/widget.py"]  # widget.py absent
    transcript = "push completed\nDeprecationWarning: foo is deprecated\n"

    advisories = analyze(report, baseline, fixture_paths, touched_paths, transcript)

    kinds = [a.kind for a in advisories]
    assert "slow_but_passing" in kinds
    assert "smell" in kinds
    assert "coverage_gap" in kinds
    assert len(advisories) == 3


def test_analyze_slow_but_passing_detail():
    report = [_op("push", p90_ms=2500, passed=True)]
    advisories = analyze(
        report, baseline=1000, fixture_paths=[], touched_paths=[], transcript=""
    )
    slow = [a for a in advisories if a.kind == "slow_but_passing"]
    assert len(slow) == 1
    assert "push" in slow[0].message
    assert slow[0].detail  # non-empty


def test_analyze_slow_not_flagged_when_failed():
    """A slow op that FAILED is a failure, not a slow-but-passing advisory."""
    report = [_op("push", p90_ms=9999, passed=False)]
    advisories = analyze(
        report, baseline=100, fixture_paths=[], touched_paths=[], transcript=""
    )
    assert all(a.kind != "slow_but_passing" for a in advisories)


def test_analyze_slow_not_flagged_when_under_baseline():
    report = [_op("push", p90_ms=50, passed=True)]
    advisories = analyze(
        report, baseline=1000, fixture_paths=[], touched_paths=[], transcript=""
    )
    assert all(a.kind != "slow_but_passing" for a in advisories)


def test_analyze_smell_patterns():
    transcript = "line one\nTODO: fix later\nFIXME: broken\n# hack: x\nnormal line\n"
    advisories = analyze(
        [], baseline=1000, fixture_paths=[], touched_paths=[], transcript=transcript
    )
    smells = [a for a in advisories if a.kind == "smell"]
    assert len(smells) == 3  # TODO, FIXME, hack


def test_analyze_coverage_gap():
    fixture_paths = ["a.py", "b.py"]
    touched_paths = ["a.py", "b.py", "c.py", "d.py"]
    advisories = analyze(
        [],
        baseline=1000,
        fixture_paths=fixture_paths,
        touched_paths=touched_paths,
        transcript="",
    )
    gaps = [a for a in advisories if a.kind == "coverage_gap"]
    gap_paths = [a.detail for a in gaps]
    assert "c.py" in gap_paths or any("c.py" in d for d in gap_paths)
    assert "d.py" in gap_paths or any("d.py" in d for d in gap_paths)
    assert len(gaps) == 2


def test_analyze_makes_no_network_call(monkeypatch):
    """analyze must be data-only: monkeypatch urlopen to raise; analyze still succeeds."""

    def _no_network(*a, **k):
        raise AssertionError("advisory.analyze must not make any network call")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    # Also patch the module-level urllib if advisory imported it.
    import testvibe.advisory as adv_mod

    if hasattr(adv_mod, "urllib"):
        monkeypatch.setattr(adv_mod.urllib.request, "urlopen", _no_network)

    report = [_op("push", p90_ms=5000, passed=True)]
    advisories = analyze(
        report,
        baseline=1000,
        fixture_paths=["a"],
        touched_paths=["a", "b"],
        transcript="Deprecated: x\n",
    )
    # Must return results without calling urlopen.
    assert len(advisories) >= 3


def test_advisory_is_dataclass():
    a = Advisory(kind="smell", message="m", detail="d")
    assert a.kind == "smell"
    assert a.message == "m"
    assert a.detail == "d"
