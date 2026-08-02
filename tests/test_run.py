"""Tests for testvibe._run — the shared run orchestrator (Task: shared run orchestrator).

``run_scenarios`` is the pytest-subprocess + tri-state-exit-code + RunReport
construction extracted from ``mcp.run_scenario`` so both the MCP tool and the
CLI ``run`` command share one orchestrator. The CLI's ``run`` runs ALL hermetic
scenarios (no ``-k`` name filter), while the MCP ``run_scenario`` selects one
by name; ``run_scenarios(name=None)`` is the all-scenarios path.

Tri-state exit-code contract (lifted from mcp.run_scenario, mirrors PLAYBOOK
infra-vs-product taxonomy):
  * pytest rc 0          -> passed=True, no failure
  * pytest rc 1          -> passed=False, failure.kind="product"
  * pytest rc 2/3/4/5 or TimeoutExpired -> passed=False, failure.kind="infra"
"""

import json
import pathlib
import textwrap


def _write_scenario_project(root: pathlib.Path, scenario_name: str, body: str) -> None:
    """Lay down a hermetic one-scenario pytest project under ``root``."""
    fn_name = "test_" + scenario_name
    (root / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (root / "test_demo.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        f"@scenario({scenario_name!r})\n"
        f"def {fn_name}():\n"
        f"    {body}\n"
    )


def test_run_scenarios_pass_returns_passed_report(tmp_path: pathlib.Path):
    """rc 0 -> RunReport(passed=True), no failures."""
    from testvibe._run import run_scenarios

    _write_scenario_project(tmp_path, "demo_pass", "assert True")
    report = run_scenarios(cwd=tmp_path)
    assert report.passed is True
    assert report.failures == []
    assert report.tool == "testvibe"
    assert report.run == "scenario:all"  # name=None -> "all" label


def test_run_scenarios_fail_returns_product_failure(tmp_path: pathlib.Path):
    """rc 1 -> RunReport(passed=False), failure.kind='product'."""
    from testvibe._run import run_scenarios

    _write_scenario_project(
        tmp_path, "demo_fail", "assert False, 'intentional failure'"
    )
    report = run_scenarios(cwd=tmp_path)
    assert report.passed is False
    assert len(report.failures) == 1
    assert report.failures[0].kind == "product"
    # A product failure must record the pytest output as detail.
    assert "intentional failure" in report.failures[0].detail


def test_run_scenarios_infra_failure_classified_infra(tmp_path: pathlib.Path):
    """rc 2 (collection error) -> failure.kind='infra', not 'product'."""
    from testvibe._run import run_scenarios

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_broken.py").write_text(
        "from testvibe import scenario\n"
        "import does_not_exist_module_xyz  # noqa: F401  # collection error\n"
        "\n"
        "@scenario('broken')\n"
        "def test_broken():\n"
        "    assert True\n"
    )
    report = run_scenarios(cwd=tmp_path)
    assert report.passed is False
    kinds = {f.kind for f in report.failures}
    assert "infra" in kinds
    assert "product" not in kinds


def test_run_scenarios_no_scenarios_is_infra(tmp_path: pathlib.Path):
    """No tests collected -> rc 5 -> infra (not product, not a silent pass)."""
    from testvibe._run import run_scenarios

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    # No test files at all -> pytest exits 5 (no tests collected).
    report = run_scenarios(cwd=tmp_path)
    assert report.passed is False
    kinds = {f.kind for f in report.failures}
    assert "infra" in kinds


def test_run_scenarios_respects_cwd(tmp_path: pathlib.Path):
    """run_scenarios must run pytest in the given cwd, not the caller's cwd."""
    from testvibe._run import run_scenarios

    _write_scenario_project(tmp_path, "cwd_check", "assert True")
    # If cwd were ignored, pytest would run in the repo root and collect a
    # different (or zero) set of scenarios. A passing report proves cwd worked.
    report = run_scenarios(cwd=tmp_path)
    assert report.passed is True


def test_run_scenarios_name_filter_selects_one(tmp_path: pathlib.Path):
    """run_scenarios(name=X) selects scenario X via pytest -k (MCP path).

    The CLI ``run`` calls with name=None (all scenarios); the MCP run_scenario
    calls with a name. Both share run_scenarios. This proves the name filter
    actually narrows the run: with two scenarios, one passing and one failing,
    selecting the passing one must return passed=True.
    """
    from testvibe._run import run_scenarios

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_demo.py").write_text(textwrap.dedent("""
        from testvibe import scenario

        @scenario('good')
        def test_good():
            assert True

        @scenario('bad')
        def test_bad():
            assert False, 'should not run'
    """))
    report = run_scenarios(cwd=tmp_path, name="good")
    assert report.passed is True


def test_run_scenarios_name_filter_excludes_others(tmp_path: pathlib.Path):
    """run_scenarios(name=X) must NOT collect a non-matching scenario.

    The negative case for the name filter: with two scenarios whose names are
    not substrings of each other, selecting one must exclude the other. Proves
    exclusion, not just inclusion — a no-op filter would also "select" the named
    one but leave the other running. Here selecting the alpha scenario must NOT
    run the beta scenario (which would fail and flip passed to False).
    """
    from testvibe._run import run_scenarios

    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    (tmp_path / "test_demo.py").write_text(textwrap.dedent("""
        from testvibe import scenario

        @scenario('alpha')
        def test_alpha():
            assert True

        @scenario('beta')
        def test_beta():
            assert False, 'beta must not run when alpha is selected'
    """))
    # alpha passes, beta fails. If the name filter leaked beta through, the run
    # would be passed=False (product failure). Selecting only alpha -> passed.
    report = run_scenarios(cwd=tmp_path, name="alpha")
    assert report.passed is True, (
        f"name filter leaked beta through: {report.failures}"
    )


def test_run_scenarios_returns_runreport_json_serializable(tmp_path: pathlib.Path):
    """The returned RunReport must to_json() cleanly (CLI prints it as markdown)."""
    from testvibe._run import run_scenarios

    _write_scenario_project(tmp_path, "json_check", "assert True")
    report = run_scenarios(cwd=tmp_path)
    # to_json + to_markdown must not raise (the CLI prints the markdown).
    parsed = json.loads(report.to_json())
    assert parsed["passed"] is True
    assert "# Testvibe Report" in report.to_markdown()


def test_run_scenarios_timeout_is_infra(monkeypatch, tmp_path: pathlib.Path):
    """A subprocess timeout -> failure.kind='infra', detail mentions 'timed out'.

    Verifies the only previously-untested tri-state branch: a hung pytest
    (subprocess.TimeoutExpired) must classify as infra, not product, and the
    detail must carry a recognizable timeout signal so a human/agent can tell a
    hang from a real assertion failure.
    """
    import subprocess

    from testvibe._run import run_scenarios

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=600)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    report = run_scenarios(cwd=tmp_path)
    assert report.passed is False
    assert len(report.failures) == 1
    assert report.failures[0].kind == "infra"
    assert "timed out" in report.failures[0].detail


# ---------------------------------------------------------------------------
# Patch B — a bad --cwd (nonexistent dir) must classify as infra, not crash.
# ---------------------------------------------------------------------------
def test_run_scenarios_nonexistent_cwd_is_infra(tmp_path: pathlib.Path):
    """A nonexistent cwd makes subprocess.run raise FileNotFoundError; that must
    be caught and classified as infra (not propagate as an uncaught traceback).

    ``testvibe run --cwd /nonexistent`` must exit 2 (infra), per the CLI
    contract — not crash with a FileNotFoundError traceback.
    """
    from testvibe._run import run_scenarios

    nonexistent = tmp_path / "does-not-exist"
    report = run_scenarios(cwd=nonexistent)
    assert report.passed is False
    assert len(report.failures) == 1
    assert report.failures[0].kind == "infra"
    # The detail should name the cwd problem so a human/agent can diagnose it.
    assert "could not run" in report.failures[0].detail or "no such file" in (
        report.failures[0].detail.lower()
    )


# ---------------------------------------------------------------------------
# Patch I — timeout must keep stderr; negative returncode must note signal death.
# ---------------------------------------------------------------------------
def test_run_scenarios_timeout_keeps_stderr(monkeypatch, tmp_path: pathlib.Path):
    """A hung pytest's stderr is the diagnostic — the TimeoutExpired handler
    must include exc.stderr in the failure detail, not discard it."""
    import subprocess

    from testvibe._run import run_scenarios

    def _raise_timeout(*args, **kwargs):
        exc = subprocess.TimeoutExpired(cmd=["pytest"], timeout=600)
        # stdout/stderr are instance attributes (not __init__ kwargs on this
        # Python version); set them so the handler can read exc.stderr.
        exc.stdout = "STDOUT_TRACE"
        exc.stderr = "STDERR_TRACE"
        raise exc

    monkeypatch.setattr(subprocess, "run", _raise_timeout)

    report = run_scenarios(cwd=tmp_path)
    assert report.passed is False
    assert report.failures[0].kind == "infra"
    detail = report.failures[0].detail
    assert "STDERR_TRACE" in detail, f"timeout detail must keep stderr: {detail!r}"
    assert "timed out" in detail


def test_run_scenarios_negative_returncode_notes_signal_death(monkeypatch, tmp_path: pathlib.Path):
    """A negative returncode (process killed by signal, e.g. -9 SIGKILL) must be
    noted in the failure detail so the report distinguishes signal death from a
    weird positive exit code, and classified as infra."""

    class _FakeProc:
        returncode = -9
        stdout = ""
        stderr = "out of memory?"

    def _fake_run(*args, **kwargs):
        return _FakeProc()

    import subprocess

    monkeypatch.setattr(subprocess, "run", _fake_run)

    from testvibe._run import run_scenarios

    report = run_scenarios(cwd=tmp_path)
    assert report.passed is False
    assert report.failures[0].kind == "infra"
    detail = report.failures[0].detail
    assert "killed by signal 9" in detail, (
        f"signal-death detail must name the signal: {detail!r}"
    )


# ---------------------------------------------------------------------------
# Patch H — Failure.detail must stay bounded ([-4000:]); full output on
# report._full_output for the advisory path.
# ---------------------------------------------------------------------------
def test_run_scenarios_failure_detail_is_bounded(monkeypatch, tmp_path: pathlib.Path):
    """Failure.detail must be bounded ([-4000:]) so a pathological pytest output
    cannot grow memory without limit. The full output lives on report._full_output."""
    from testvibe._run import run_scenarios

    # Build a scenario whose failure produces a large stdout (>4000 chars).
    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # noqa: F401\n")
    big = "X" * 8000
    (tmp_path / "test_big.py").write_text(
        "from testvibe import scenario\n"
        "\n"
        "@scenario('big')\n"
        "def test_big():\n"
        f"    assert False, {big!r}\n"
    )
    report = run_scenarios(cwd=tmp_path)
    assert report.passed is False
    detail = report.failures[0].detail
    # Bounded: the detail must NOT contain the full 8000-char blob verbatim.
    assert len(detail) <= 4000 + 200, (  # small slack for surrounding message
        f"Failure.detail unbounded: len={len(detail)}"
    )
    # The full transcript is reachable for the advisory analyzer.
    full = getattr(report, "_full_output", "")
    assert big in full, "full output must be reachable on report._full_output"
