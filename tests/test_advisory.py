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


def test_analyze_smell_matches_deprecation_warning():
    """``DeprecationWarning`` is Python's canonical deprecation signal and must
    be flagged as a smell (regression guard on the smell regex).
    """
    transcript = "DeprecationWarning: use baz() instead"
    advisories = analyze(
        [], baseline=1000, fixture_paths=[], touched_paths=[], transcript=transcript
    )
    smells = [a for a in advisories if a.kind == "smell"]
    assert len(smells) == 1


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
    """analyze is data-only: it must not open ANY socket or URL.

    Guards two egress vectors so a future regression cannot slip in via a
    different network library than urllib:

    (1) dynamic  — monkeypatch ``socket.socket`` to raise on construction AND
                   ``urllib.request.urlopen`` to raise; ``analyze`` still
                   returns its advisories without raising.
    (2) static   — ``advisory.py``'s own source must import no network module
                   (``socket``/``urllib``/``http``/``requests``/``urllib3``/``ssl``),
                   catching the regression at the source regardless of how the
                   call is made.
    """
    # --- (1) dynamic guards: any socket construction or URL open blows up. ---
    import socket
    import urllib.request

    def _no_socket(*a, **k):
        raise AssertionError("advisory.analyze must not open any socket")

    def _no_urlopen(*a, **k):
        raise AssertionError("advisory.analyze must not open any URL")

    monkeypatch.setattr(socket, "socket", _no_socket)
    monkeypatch.setattr(urllib.request, "urlopen", _no_urlopen)

    report = [_op("push", p90_ms=5000, passed=True)]
    advisories = analyze(
        report,
        baseline=1000,
        fixture_paths=["a"],
        touched_paths=["a", "b"],
        transcript="Deprecated: x\n",
    )
    # Must return results without opening any socket / URL.
    assert len(advisories) >= 3

    # --- (2) static guard: advisory.py imports no network module. ---
    import inspect
    import re as _re

    import testvibe.advisory as adv_mod

    source = inspect.getsource(adv_mod)
    forbidden = {"socket", "urllib", "http", "requests", "urllib3", "ssl"}
    imported = set()
    for line in source.splitlines():
        m = _re.match(r"\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", line)
        if m:
            imported.add(m.group(1))
    network_imports = imported & forbidden
    assert not network_imports, (
        f"advisory.py must not import network modules; found: {sorted(network_imports)}"
    )


def test_advisory_is_dataclass():
    a = Advisory(kind="smell", message="m", detail="d")
    assert a.kind == "smell"
    assert a.message == "m"
    assert a.detail == "d"
