"""Tests for the captured-failure corpus + quarantine auto-pin (Task A4).

Verifies:
  * ``load_corpus`` filters to open/pinned entries and returns [] when the
    file is missing,
  * ``quarantine_tests_for`` yields ``(test_name, repro_callable, status)``
    tuples whose repro is executable,
  * the plugin's ``pytest_collect_file`` hook collects ``known-failures.yaml``
    into ``@pytest.mark.quarantine`` xfail(strict=True) tests,
  * a passing pinned repro surfaces as an XPASS under strict xfail (the
    promotion signal),
  * normal collection is unaffected when ``known-failures.yaml`` is absent.
"""

import pathlib
import subprocess
import sys
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Plan snippet (A4 Step 1) — the canonical acceptance test.
# ---------------------------------------------------------------------------
def test_pinned_passing_entry_signals_promotion(tmp_path: pathlib.Path):
    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    (tmp_path / "known-failures.yaml").write_text(textwrap.dedent(f"""
        - id: demo-fixed
          invariant: demo
          discovered_at: 2026-07-30
          source: test
          repro: {repro}
          status: pinned
    """))
    from testvibe.corpus import load_corpus, quarantine_tests_for

    tests = quarantine_tests_for(load_corpus(tmp_path / "known-failures.yaml"))
    assert tests[0][0] == "test_quarantine__demo_fixed"
    assert tests[0][1]() is True   # repro passes -> xpass under xfail(strict) -> promote
    assert tests[0][2] == "pinned"


# ---------------------------------------------------------------------------
# load_corpus edge cases.
# ---------------------------------------------------------------------------
def test_load_corpus_missing_file_returns_empty(tmp_path: pathlib.Path):
    from testvibe.corpus import load_corpus

    assert load_corpus(tmp_path / "does-not-exist.yaml") == []


def test_load_corpus_filters_out_non_open_pinned(tmp_path: pathlib.Path):
    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    (tmp_path / "known-failures.yaml").write_text(textwrap.dedent(f"""
        - id: a-open
          invariant: inv
          discovered_at: 2026-07-30
          source: t
          repro: {repro}
          status: open
        - id: b-pinned
          invariant: inv
          discovered_at: 2026-07-30
          source: t
          repro: {repro}
          status: pinned
        - id: c-fixed
          invariant: inv
          discovered_at: 2026-07-30
          source: t
          repro: {repro}
          status: fixed
        - id: d-ignored
          invariant: inv
          discovered_at: 2026-07-30
          source: t
          repro: {repro}
          status: ignored
    """))
    from testvibe.corpus import load_corpus

    entries = load_corpus(tmp_path / "known-failures.yaml")
    ids = [e.id for e in entries]
    assert ids == ["a-open", "b-pinned"]


def test_load_corpus_empty_file_returns_empty(tmp_path: pathlib.Path):
    from testvibe.corpus import load_corpus

    (tmp_path / "known-failures.yaml").write_text("")
    assert load_corpus(tmp_path / "known-failures.yaml") == []


# ---------------------------------------------------------------------------
# Malformed-input resilience — load_corpus must raise a clear, named
# CorpusError (never a cryptic AttributeError / TypeError / yaml.YAMLError) so
# the plugin's collection hook can catch it and skip the quarantine set
# instead of aborting the whole pytest run.
# ---------------------------------------------------------------------------
def test_load_corpus_top_level_mapping_raises_corpus_error(tmp_path: pathlib.Path):
    from testvibe.corpus import CorpusError, load_corpus

    (tmp_path / "known-failures.yaml").write_text("id: not-a-list\ninvariant: x\n")
    with pytest.raises(CorpusError):
        load_corpus(tmp_path / "known-failures.yaml")


def test_load_corpus_entry_missing_fields_raises_corpus_error(tmp_path: pathlib.Path):
    from testvibe.corpus import CorpusError, load_corpus

    (tmp_path / "known-failures.yaml").write_text(textwrap.dedent("""
        - id: incomplete
          status: open
    """))
    with pytest.raises(CorpusError):
        load_corpus(tmp_path / "known-failures.yaml")


def test_load_corpus_malformed_yaml_raises_corpus_error(tmp_path: pathlib.Path):
    from testvibe.corpus import CorpusError, load_corpus

    (tmp_path / "known-failures.yaml").write_text(
        " - id: broken\n    bad: [unterminated\n"
    )
    with pytest.raises(CorpusError):
        load_corpus(tmp_path / "known-failures.yaml")


# ---------------------------------------------------------------------------
# Plugin collection hook (pytest_collect_file) for known-failures.yaml.
# ---------------------------------------------------------------------------
def test_quarantine_collected_from_yaml(tmp_path: pathlib.Path):
    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    (tmp_path / "known-failures.yaml").write_text(textwrap.dedent(f"""
        - id: demo-fixed
          invariant: demo
          discovered_at: 2026-07-30
          source: test
          repro: {repro}
          status: pinned
    """))
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "--collect-only", "-q"],
        capture_output=True, text=True, check=True,
    )
    assert "test_quarantine__demo_fixed" in out.stdout


def test_collection_works_when_yaml_absent(tmp_path: pathlib.Path):
    """The plugin's collect hook must not break normal collection."""
    (tmp_path / "test_plain.py").write_text("def test_ok():\n    assert True\n")
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "--collect-only", "-q"],
        capture_output=True, text=True, check=True,
    )
    assert "test_ok" in out.stdout


def test_passing_pinned_repro_xpasses_strict_and_fails(tmp_path: pathlib.Path):
    """A pinned repro that now passes must XPASS under strict xfail -> non-zero
    exit. That non-zero exit IS the promotion signal in CI."""
    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    (tmp_path / "known-failures.yaml").write_text(textwrap.dedent(f"""
        - id: demo-fixed
          invariant: demo
          discovered_at: 2026-07-30
          source: test
          repro: {repro}
          status: pinned
    """))
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q"],
        capture_output=True, text=True,
    )
    # XPASS under strict=True is treated as a failure -> exit 1
    assert out.returncode != 0, out.stdout + out.stderr
    assert "test_quarantine__demo_fixed" in out.stdout


def test_failing_open_repro_xfails_and_passes(tmp_path: pathlib.Path):
    """A still-failing open repro is xfailed (expected failure) -> exit 0."""
    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('still broken')\n")
    (tmp_path / "known-failures.yaml").write_text(textwrap.dedent(f"""
        - id: demo-open
          invariant: demo
          discovered_at: 2026-07-30
          source: test
          repro: {repro}
          status: open
    """))
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "1 xfailed" in out.stdout


def test_malformed_known_failures_yaml_does_not_break_collection(tmp_path: pathlib.Path):
    # A malformed known-failures.yaml must NOT abort the whole pytest run — the
    # plugin catches CorpusError, warns, and skips the quarantine items, so the
    # rest of the suite collects normally.
    (tmp_path / "known-failures.yaml").write_text("id: not-a-list\ninvariant: x\n")
    (tmp_path / "test_plain.py").write_text("def test_ok():\n    assert True\n")
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "--collect-only", "-q"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "test_ok" in out.stdout
