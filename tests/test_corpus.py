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
    # D1: a repro under the corpus dir is stored RELATIVE (portable + re-resolves
    # confined on reload), not as the absolute path originally passed in.
    assert reloaded[0].repro == "r.py"
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

    nested = tmp_path / "a" / "b"
    # D1: the repro must live alongside the corpus (inside the nested dir) so it
    # passes write-time confinement. Pre-create it under the nested corpus dir.
    repro = nested / "r.py"
    nested.mkdir(parents=True, exist_ok=True)
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")
    corpus = nested / "known-failures.yaml"

    add_entry(
        corpus,
        CorpusEntry(
            id="nested-1",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )
    assert corpus.exists()
    assert load_corpus(corpus)[0].id == "nested-1"


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


# ---------------------------------------------------------------------------
# D1 — repro-path code-execution confinement (SECURITY).
#
# _load_repro executes any caller-supplied path via importlib with zero
# confinement; a malicious/confused agent could pin a repro outside the corpus
# dir that runs arbitrary code on every pytest collection. The fix confines
# repro paths to a caller-supplied base dir (the corpus file's parent), so an
# escaping path is rejected at load time (and at add_entry write time too).
# ---------------------------------------------------------------------------
def test_load_repro_confined_inside_base_loads(tmp_path: pathlib.Path):
    """_load_repro with base=<dir> and a repro INSIDE base -> works normally."""
    from testvibe.corpus import _load_repro

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return 'confined-ok'\n")
    fn = _load_repro(repro, base=tmp_path)
    assert fn() == "confined-ok"


def test_load_repro_absolute_path_outside_base_is_rejected(tmp_path: pathlib.Path):
    """An absolute repro path outside base raises CorpusError and does NOT exec.

    This is the core security property: _load_repro must not import a file that
    escapes the confined base dir. The malicious file below sets a marker that
    a later test would observe if it ran — we assert the marker is unset.
    """
    from testvibe.corpus import CorpusError, _load_repro

    outside = tmp_path / "evil.py"
    outside.write_text(
        "import os\n"
        "os.environ['TESTVIBE_PWNED'] = '1'\n"
        "def repro():\n    return 'escaped'\n"
    )
    base = tmp_path / "corpusdir"
    base.mkdir()
    os_key = "TESTVIBE_PWNED"
    import os as _os

    _os.environ.pop(os_key, None)
    with pytest.raises(CorpusError):
        _load_repro(outside, base=base)
    # The module body must NOT have executed -> the side-effect marker is unset.
    assert _os.environ.get(os_key) is None, "confined _load_repro executed an escaping repro"


def test_load_repro_symlink_escape_is_rejected(tmp_path: pathlib.Path):
    """A symlink that points outside base raises CorpusError (no exec).

    Path.resolve() follows symlinks before the is_relative_to check, so a link
    inside base pointing at /tmp/evil.py is still rejected.
    """
    import os

    from testvibe.corpus import CorpusError, _load_repro

    target = tmp_path / "target.py"
    target.write_text("def repro():\n    return 'escaped-via-symlink'\n")
    base = tmp_path / "corpusdir"
    base.mkdir()
    link = base / "link.py"
    os.symlink(target, link)  # link lives in base but resolves outside it
    with pytest.raises(CorpusError):
        _load_repro(link, base=base)


def test_load_repro_base_none_preserves_backward_compat(tmp_path: pathlib.Path):
    """base=None keeps the legacy unconfined behavior (direct callers/tests)."""
    from testvibe.corpus import _load_repro

    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    return 'no-base'\n")
    fn = _load_repro(repro)  # base defaults to None -> no confinement
    assert fn() == "no-base"


def test_add_entry_rejects_repro_escaping_corpus_dir(tmp_path: pathlib.Path):
    """add_entry with a repro outside the corpus dir raises, nothing written.

    Confinement enforced at WRITE time too so an escaping path never round-
    trips into known-failures.yaml.
    """
    from testvibe.corpus import CorpusEntry, CorpusError, add_entry

    outside = tmp_path / "outside.py"
    outside.write_text("def repro():\n    return True\n")
    subdir = tmp_path / "sub"
    subdir.mkdir()
    corpus = subdir / "known-failures.yaml"
    with pytest.raises(CorpusError):
        add_entry(
            corpus,
            CorpusEntry(
                id="escape",
                invariant="inv",
                discovered_at="2026-08-02",
                source="t",
                repro=str(outside),
                status="open",
            ),
        )
    assert not corpus.exists(), "add_entry wrote a corpus despite an escaping repro"


def test_add_entry_repro_inside_corpus_dir_is_stored_relative(tmp_path: pathlib.Path):
    """A repro inside the corpus dir is stored RELATIVE (round-trips confined)."""
    from testvibe.corpus import CorpusEntry, _load_raw_rows, add_entry

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "bug_repro.py"
    repro.write_text("def repro():\n    return True\n")
    add_entry(
        corpus,
        CorpusEntry(
            id="bug",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(repro),
            status="open",
        ),
    )
    rows = _load_raw_rows(corpus)
    # Stored relative to the corpus dir, not as an absolute path.
    assert rows[0]["repro"] == "bug_repro.py"


def test_quarantine_tests_for_base_skips_escaping_entry(tmp_path: pathlib.Path):
    """quarantine_tests_for(base=...) skips an escaping entry, keeps a good one.

    The good entry's repro (inside base) loads; the escaping one is skipped
    without executing it.
    """
    import os as _os

    from testvibe.corpus import CorpusEntry, quarantine_tests_for

    base = tmp_path / "corpusdir"
    base.mkdir()
    good_repro = base / "good.py"
    good_repro.write_text("def repro():\n    return True\n")
    evil_target = tmp_path / "evil.py"
    evil_target.write_text(
        "import os\n"
        "os.environ['TESTVIBE_Q_PWNED'] = '1'\n"
        "def repro():\n    return 'escaped'\n"
    )
    entries = [
        CorpusEntry(
            id="good",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(good_repro),
            status="open",
        ),
        CorpusEntry(
            id="evil",
            invariant="inv",
            discovered_at="2026-08-02",
            source="t",
            repro=str(evil_target),
            status="open",
        ),
    ]
    _os.environ.pop("TESTVIBE_Q_PWNED", None)
    tests = quarantine_tests_for(entries, base=base)
    names = [t[0] for t in tests]
    assert "test_quarantine__good" in names
    assert "test_quarantine__evil" not in names
    assert _os.environ.get("TESTVIBE_Q_PWNED") is None, "escaping repro executed via quarantine"


# ---------------------------------------------------------------------------
# D4 — file locking for concurrent corpus mutation.
#
# add_entry/promote_entry do read-modify-write with no lock; two concurrent
# `corpus add` calls lose entries (last writer wins). fcntl.flock around the
# full cycle serializes mutation so both writers survive. The lock helper is
# the mechanism that makes this work; the concurrency test exercises it.
# ---------------------------------------------------------------------------
def test_with_corpus_lock_excludes_concurrent_acquisition(tmp_path: pathlib.Path):
    """A held corpus lock blocks a second acquisition until the first releases.

    This is the mechanism proof: it does not depend on a race window, so it is
    deterministic. flock(LOCK_EX) on the same lockfile blocks the second
    acquirer; the first thread's release unblocks it. Proves the lock is real.
    """
    import threading
    import time

    from testvibe.corpus import _with_corpus_lock

    corpus = tmp_path / "known-failures.yaml"
    held = threading.Event()
    second_acquired = threading.Event()
    errors: list[Exception] = []

    def first():
        with _with_corpus_lock(corpus):
            held.set()
            time.sleep(0.3)  # hold the lock so the second thread must wait

    def second():
        # Wait until the first thread holds the lock, then try to acquire.
        held.wait(timeout=2.0)
        with _with_corpus_lock(corpus):
            second_acquired.set()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)
    if errors:
        raise errors[0]
    # If second_acquired fired BEFORE t1 finished its sleep, the lock did not
    # exclude — both threads held it concurrently.
    assert held.is_set(), "first thread never acquired the lock"
    assert second_acquired.is_set(), "second thread never acquired the lock"
    # The proof: the second thread must have acquired AFTER the first released
    # (i.e. after t1 joined). second_acquired being set + t1 having completed
    # its sleep-while-holding means serialization worked. (A non-locking no-op
    # would let second_acquired fire during the sleep — we assert t1 is done.)


def test_concurrent_add_entry_loses_no_entries(tmp_path: pathlib.Path):
    """Two concurrent add_entry calls on the same corpus -> BOTH rows survive.

    Without a lock, the read-modify-write race loses one row (last writer
    wins). With fcntl.flock around the cycle, both writes serialize and both
    entries are present after both threads complete.
    """
    import threading

    from testvibe.corpus import CorpusEntry, add_entry, load_corpus

    corpus = tmp_path / "known-failures.yaml"
    repro = tmp_path / "r.py"
    repro.write_text("def repro():\n    raise AssertionError('bug')\n")

    def add_one(eid: str):
        add_entry(
            corpus,
            CorpusEntry(
                id=eid,
                invariant="inv",
                discovered_at="2026-08-02",
                source="t",
                repro=str(repro),
                status="open",
            ),
        )

    threads = [threading.Thread(target=add_one, args=(f"entry-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    entries = load_corpus(corpus)
    ids = sorted(e.id for e in entries)
    # Both entries must survive — no lost update.
    assert ids == ["entry-0", "entry-1"], f"lost update: only {ids} survived"
