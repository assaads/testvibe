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
# add_entry on a corrupt corpus — must RAISE, not silently overwrite.
#
# _load_raw_rows previously swallowed malformed YAML / non-list top-level to
# [], so add_entry on a hand-edited-but-broken known-failures.yaml loaded [],
# appended one row, and dumped it — destroying the original. These guard the
# fix: add_entry refuses to mutate a present-but-corrupt file.
# ---------------------------------------------------------------------------
def test_add_entry_corrupt_yaml_raises_and_does_not_overwrite(tmp_path: pathlib.Path):
    """add_entry on unparseable YAML raises CorpusError, preserves the file."""
    from testvibe.corpus import CorpusEntry, add_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"
    original = " - id: broken\n    bad: [unterminated\n"
    corpus.write_text(original)

    with pytest.raises(Exception):  # CorpusError
        add_entry(
            corpus,
            CorpusEntry(
                id="x",
                invariant="inv",
                discovered_at="2026-08-02",
                source="t",
                repro=str(repro),
                status="open",
            ),
        )
    # The corrupt original must be untouched (not overwritten with a single row).
    assert corpus.read_text() == original


def test_add_entry_top_level_mapping_raises_corpus_error(tmp_path: pathlib.Path):
    """add_entry on a file whose top-level is a mapping raises, not overwrites."""
    from testvibe.corpus import CorpusEntry, CorpusError, add_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"
    corpus.write_text("id: not-a-list\ninvariant: x\n")

    with pytest.raises(CorpusError):
        add_entry(
            corpus,
            CorpusEntry(
                id="x",
                invariant="inv",
                discovered_at="2026-08-02",
                source="t",
                repro=str(repro),
                status="open",
            ),
        )
    # Original mapping preserved, not replaced with a list.
    assert corpus.read_text() == "id: not-a-list\ninvariant: x\n"


def test_add_entry_missing_file_still_succeeds(tmp_path: pathlib.Path):
    """add_entry on a genuinely-absent file creates it (not treated as corrupt)."""
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"
    assert not corpus.exists()  # genuinely missing, not corrupt

    add_entry(
        corpus,
        CorpusEntry(
            id="fresh",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )
    entries = load_corpus(corpus)
    assert len(entries) == 1
    assert entries[0].id == "fresh"


# ---------------------------------------------------------------------------
# add_entry status validation — only 'open'/'pinned' accepted at the chokepoint.
# ---------------------------------------------------------------------------
def test_add_entry_rejects_invalid_status(tmp_path: pathlib.Path):
    """add_entry with status='fixed' raises CorpusError (would be invisible on reload)."""
    from testvibe.corpus import CorpusEntry, CorpusError, add_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"

    with pytest.raises(CorpusError):
        add_entry(
            corpus,
            CorpusEntry(
                id="x",
                invariant="inv",
                discovered_at="2026-08-02",
                source="t",
                repro=str(repro),
                status="fixed",  # load_corpus drops this; must be rejected at write
            ),
        )


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


# ---------------------------------------------------------------------------
# Write API (Task: corpus write fns) — add_entry / promote_entry / _dump_corpus.
#
# These are the mutation half the corpus.py docstring promised but shipped
# without: load_corpus is read-only today. The CLI `corpus add`/`promote` and
# the MCP append tool both route through these so known-failures.yaml has ONE
# mutation path. Round-trips through load_corpus because that's the reader the
# pytest plugin uses — a row that doesn't reload is worse than useless.
# ---------------------------------------------------------------------------
def test_add_entry_round_trips_through_load_corpus(tmp_path: pathlib.Path):
    """add_entry appends a row whose fields load_corpus reloads verbatim."""
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"

    entry = add_entry(
        corpus,
        CorpusEntry(
            id="bug-1",
            invariant="push is idempotent",
            discovered_at="2026-08-02",
            source="test",
            repro=str(repro),
            status="open",
        ),
    )
    assert entry.id == "bug-1"
    assert entry.status == "open"

    reloaded = load_corpus(corpus)
    assert len(reloaded) == 1
    assert reloaded[0].id == "bug-1"
    assert reloaded[0].invariant == "push is idempotent"
    assert reloaded[0].repro == str(repro)
    assert reloaded[0].status == "open"


def test_add_entry_appends_to_existing_corpus(tmp_path: pathlib.Path):
    """add_entry must append, not overwrite, existing rows."""
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"
    corpus.parent.mkdir(parents=True, exist_ok=True)

    add_entry(
        corpus,
        CorpusEntry(
            id="first",
            invariant="inv-a",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )
    add_entry(
        corpus,
        CorpusEntry(
            id="second",
            invariant="inv-b",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="pinned",
        ),
    )

    reloaded = load_corpus(corpus)
    ids = [e.id for e in reloaded]
    assert ids == ["first", "second"]


def test_add_entry_creates_parent_directory(tmp_path: pathlib.Path):
    """add_entry must mkdir -p the parent so a fresh tests/ dir works."""
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    nested = tmp_path / "a" / "b" / "known-failures.yaml"

    add_entry(
        nested,
        CorpusEntry(
            id="nested-1",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )
    assert nested.exists()
    assert load_corpus(nested)[0].id == "nested-1"


def test_promote_entry_flips_pinned_to_fixed_after_green(tmp_path: pathlib.Path):
    """promote_entry(passes=True) flips pinned -> fixed (the only promotion path).

    Per PLAYBOOK: promotion is the ONLY path pinned -> fixed, and ONLY after a
    deterministic green re-run. passes=True is that green signal.
    """
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus, promote_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    corpus = tmp_path / "known-failures.yaml"

    add_entry(
        corpus,
        CorpusEntry(
            id="bug-2",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="pinned",
        ),
    )

    promoted = promote_entry(corpus, "bug-2", passes=True)
    assert promoted.id == "bug-2"
    assert promoted.status == "fixed"

    # fixed entries drop out of the active quarantine set (load_corpus filters
    # to open/pinned), so the promotion is observable as an empty reload.
    assert load_corpus(corpus) == []


def test_promote_entry_not_green_is_noop(tmp_path: pathlib.Path):
    """promote_entry(passes=False) must NOT flip status — the bug isn't fixed yet.

    Per PLAYBOOK: promotion only after a deterministic green re-run. A non-green
    signal means the repro still fails, so flipping to fixed would be fraud.
    """
    from testvibe.corpus import CorpusEntry, add_entry, load_corpus, promote_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('still broken')\n")
    corpus = tmp_path / "known-failures.yaml"

    add_entry(
        corpus,
        CorpusEntry(
            id="bug-3",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="pinned",
        ),
    )

    promoted = promote_entry(corpus, "bug-3", passes=False)
    # No-op: status unchanged, still in the active quarantine set.
    assert promoted.status == "pinned"
    reloaded = load_corpus(corpus)
    assert len(reloaded) == 1
    assert reloaded[0].status == "pinned"


def test_promote_entry_unknown_id_raises(tmp_path: pathlib.Path):
    """promote_entry on a missing id must raise (not silently no-op)."""
    from testvibe.corpus import CorpusEntry, add_entry, promote_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    corpus = tmp_path / "known-failures.yaml"
    add_entry(
        corpus,
        CorpusEntry(
            id="real",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="pinned",
        ),
    )

    from testvibe.corpus import CorpusError

    with pytest.raises(CorpusError):
        promote_entry(corpus, "does-not-exist", passes=True)


def test_promote_entry_works_on_open_status(tmp_path: pathlib.Path):
    """promote_entry also promotes open -> fixed (any active quarantine state).

    Promotion isn't restricted to pinned; an open entry that re-runs green is
    also fixed. The PLAYBOOK invariant is "only after green," not "only pinned."
    """
    from testvibe.corpus import CorpusEntry, add_entry, promote_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    corpus = tmp_path / "known-failures.yaml"
    add_entry(
        corpus,
        CorpusEntry(
            id="bug-open",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )

    promoted = promote_entry(corpus, "bug-open", passes=True)
    assert promoted.status == "fixed"


def test_promote_entry_already_fixed_is_idempotent(tmp_path: pathlib.Path):
    """Promoting an already-fixed entry is a no-op success (idempotent)."""
    from testvibe.corpus import CorpusEntry, add_entry, promote_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return True\n")
    corpus = tmp_path / "known-failures.yaml"
    add_entry(
        corpus,
        CorpusEntry(
            id="bug-fixed",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )
    promote_entry(corpus, "bug-fixed", passes=True)
    # Second promotion — still fixed, no error.
    again = promote_entry(corpus, "bug-fixed", passes=True)
    assert again.status == "fixed"


def test_promote_entry_missing_corpus_raises(tmp_path: pathlib.Path):
    """promote_entry on a corpus file that doesn't exist must raise."""
    from testvibe.corpus import CorpusError, promote_entry

    with pytest.raises(CorpusError):
        promote_entry(tmp_path / "no-such.yaml", "anything", passes=True)


# ---------------------------------------------------------------------------
# Patch C — quarantine_tests_for must skip a broken repro, not abort collection.
# ---------------------------------------------------------------------------
def test_quarantine_tests_for_skips_broken_repro_keeps_good(tmp_path: pathlib.Path):
    """A single broken repro (missing file) must not abort quarantine collection.

    quarantine_tests_for must skip the entry whose repro cannot be loaded and
    return ONLY the good entry's tuple, honoring the docstring promise that "a
    broken corpus degrades to a skipped quarantine set instead of aborting."
    """
    from testvibe.corpus import CorpusEntry, quarantine_tests_for

    good_repro = tmp_path / "good.py"
    good_repro.write_text("def repro():\n    return True\n")
    entries = [
        CorpusEntry(
            id="good-one",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(good_repro),
            status="open",
        ),
        CorpusEntry(
            id="broken-one",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(tmp_path / "does-not-exist.py"),  # missing repro
            status="open",
        ),
    ]
    tests = quarantine_tests_for(entries)
    # Only the good entry survives; the broken one is skipped (not raised).
    assert len(tests) == 1
    assert tests[0][0] == "test_quarantine__good_one"


# ---------------------------------------------------------------------------
# Patch D — add_entry must reject duplicate ids.
# ---------------------------------------------------------------------------
def test_add_entry_rejects_duplicate_id(tmp_path: pathlib.Path):
    """add_entry twice with the same id -> second raises CorpusError.

    A duplicate id creates duplicate pytest test names and zombie pins (promote
    matches only the first). Must be rejected at the write chokepoint.
    """
    from testvibe.corpus import CorpusEntry, CorpusError, add_entry, load_corpus

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"

    add_entry(
        corpus,
        CorpusEntry(
            id="dup",
            invariant="first",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )
    with pytest.raises(CorpusError):
        add_entry(
            corpus,
            CorpusEntry(
                id="dup",
                invariant="second",
                discovered_at="2026-08-02",
                source="t",
                repro=str(repro),
                status="open",
            ),
        )
    # The corpus must still have exactly ONE row (the first), not two.
    entries = load_corpus(corpus)
    assert len(entries) == 1
    assert entries[0].id == "dup"
    assert entries[0].invariant == "first"


# ---------------------------------------------------------------------------
# Patch F — _load_raw_rows must fail loud on a non-dict row (not silently drop).
# ---------------------------------------------------------------------------
def test_load_corpus_non_dict_row_raises(tmp_path: pathlib.Path):
    """A corpus YAML list containing a non-dict element (e.g. a bare string)
    must raise CorpusError, not silently strip it.

    Silently stripping non-dict rows contradicts the fail-loud-on-corrupt
    behavior shipped for malformed YAML; a list with a non-dict element is
    corruption, not a filter case.
    """
    from testvibe.corpus import CorpusError, load_corpus

    (tmp_path / "known-failures.yaml").write_text(
        "- id: ok\n  status: open\n  invariant: i\n"
        "  discovered_at: '2026-08-02'\n  source: t\n  repro: r.py\n"
        "- bare-string-not-a-mapping\n"
    )
    with pytest.raises(CorpusError):
        load_corpus(tmp_path / "known-failures.yaml")


def test_load_raw_rows_non_dict_row_raises(tmp_path: pathlib.Path):
    """The mutation-path loader (_load_raw_rows) must also fail loud on a
    non-dict row, so add_entry on a corrupted corpus refuses to overwrite it."""
    from testvibe.corpus import CorpusError, _load_raw_rows
    from pathlib import Path

    (tmp_path / "known-failures.yaml").write_text("- id: ok\n- bare-string\n")
    with pytest.raises(CorpusError):
        _load_raw_rows(Path(tmp_path / "known-failures.yaml"))


# ---------------------------------------------------------------------------
# Patch L — add_entry must validate the id charset (quarantine test-name safety).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_id",
    [
        "bad/id",      # slash
        "bad id",      # space
        "bad.id",      # dot
        "9leading",    # leading digit
        "",            # empty
    ],
)
def test_add_entry_rejects_unsafe_id_charset(tmp_path: pathlib.Path, bad_id: str):
    """An id that cannot yield a valid pytest test name must be rejected.

    quarantine_tests_for builds test_quarantine__{id.replace('-','_')} with no
    other sanitization; ids with spaces/dots/slashes/leading-digits produce
    invalid python identifiers. Must be rejected at the write chokepoint.
    """
    from testvibe.corpus import CorpusEntry, CorpusError, add_entry

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = tmp_path / "known-failures.yaml"

    with pytest.raises(CorpusError):
        add_entry(
            corpus,
            CorpusEntry(
                id=bad_id,
                invariant="inv",
                discovered_at="2026-08-02",
                source="t",
                repro=str(repro),
                status="open",
            ),
        )
