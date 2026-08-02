"""Captured-failure corpus + quarantine auto-pin (Task A4 / Spec S7).

A ``known-failures.yaml`` file records previously-observed failures as a list
of entries. Each entry pins a *repro* (a ``def repro():`` callable in a plain
``.py`` file) that re-exercises the bug. The plugin re-runs every open/pinned
repro as an ``xfail(strict=True)`` test: a still-failing repro is quietly
xfailed (expected), while a now-passing repro XPASSes — under strict, that
fails CI and is the signal to promote the entry to ``status: fixed``.

This is the self-growing net: every captured regression becomes a permanent,
automatically-verified pin until it is provably fixed.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class CorpusEntry:
    """One row in ``known-failures.yaml``."""

    id: str
    invariant: str
    discovered_at: str
    source: str
    repro: str
    status: str


class CorpusError(Exception):
    """Raised when a ``known-failures.yaml`` corpus cannot be loaded.

    Covers the three malformed-input shapes that previously surfaced as cryptic
    errors during pytest collection: top-level YAML that is not a list of
    mappings (was ``AttributeError``), an entry missing required fields (was
    ``TypeError``), and unparseable YAML (was ``yaml.YAMLError``). Callers —
    notably the pytest plugin's collection hook — catch this so a broken corpus
    degrades to a skipped quarantine set instead of aborting the whole run.
    """


# Fields every corpus entry must carry. Centralized so validation and the
# ``CorpusEntry`` dataclass cannot drift apart.
_REQUIRED_FIELDS = ("id", "invariant", "discovered_at", "source", "repro", "status")

# pytest-safe id charset: ``quarantine_tests_for`` builds ``test_quarantine__{id}``
# with only ``-`` -> ``_`` substitution, so an id with spaces/dots/slashes/leading
# digits yields an invalid python identifier. Allow letters, digits, ``_`` and
# ``-``, but require a non-digit first character (mirrors python identifier rules
# so the derived test name is always valid).
_SAFE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


def load_corpus(path) -> list[CorpusEntry]:
    """Load a ``known-failures.yaml`` corpus, keeping only open/pinned entries.

    Returns ``[]`` when the file is missing or empty — so callers (and the
    plugin's collection hook) never have to special-case absence.

    Raises ``CorpusError`` (never a bare ``AttributeError`` / ``TypeError`` /
    ``yaml.YAMLError``) when the file is structurally invalid — malformed YAML,
    a top-level structure that is not a list, an entry that is not a mapping,
    or an open/pinned entry missing required fields. Downgrades to ``[]`` via
    the plugin's collection hook, so a broken corpus never aborts pytest.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        raise CorpusError(f"malformed YAML in {p}: {e}") from e
    if raw is None:  # empty file
        return []
    if not isinstance(raw, list):
        raise CorpusError(
            f"expected a top-level YAML list in {p}, got {type(raw).__name__}"
        )

    entries: list[CorpusEntry] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise CorpusError(
                f"entry #{i} in {p} is not a mapping (got {type(entry).__name__})"
            )
        # Filter by status BEFORE validating completeness, so legacy fixed /
        # ignored entries with missing fields don't poison the whole load.
        if entry.get("status") not in ("open", "pinned"):
            continue
        missing = [f for f in _REQUIRED_FIELDS if f not in entry]
        if missing:
            raise CorpusError(
                f"entry #{i} in {p} (id={entry.get('id')!r}) missing fields: {missing}"
            )
        try:
            entries.append(CorpusEntry(**entry))
        except TypeError as ex:
            raise CorpusError(
                f"entry #{i} in {p} (id={entry.get('id')!r}) invalid: {ex}"
            ) from ex
    return entries


def _load_repro(repro_path):
    """Import ``repro_path`` from disk and return its ``repro`` callable."""
    rp = Path(repro_path)
    spec = importlib.util.spec_from_file_location(rp.stem, rp)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None  # for type-checkers; spec_from_file_location sets a loader
    spec.loader.exec_module(mod)
    return mod.repro


# ---------------------------------------------------------------------------
# Mutation API — the write half of known-failures.yaml.
#
# This is the SINGLE mutation path for the corpus: the CLI ``corpus add`` /
# ``corpus promote`` and the MCP ``add_corpus_entry`` / ``promote_corpus`` tools
# all route through ``add_entry`` / ``promote_entry`` so read/write semantics
# cannot drift (previously mcp.py carried its own ``_dump_raw_yaml`` which wrote
# raw dicts, bypassing the ``CorpusEntry`` schema). Loads as raw rows (not via
# ``load_corpus``, which filters to open/pinned and would silently drop fixed /
# ignored entries on rewrite), mutates, dumps.
# ---------------------------------------------------------------------------


def _dump_corpus(path: Path, rows: list[dict]) -> None:
    """Persist corpus rows atomically, creating the parent directory if needed.

    Writes to a temp file in the SAME directory then ``os.replace``s it onto
    ``path``. ``os.replace`` is atomic on POSIX, so an interrupted write cannot
    leave a truncated ``known-failures.yaml`` that the reader would then
    swallow as ``[]`` (silent total data loss). The temp file is in the same
    directory so the rename is a single-filesystem atomic operation.

    Mirrors the former ``mcp._dump_raw_yaml`` shape (``yaml.safe_dump`` with
    ``sort_keys=False`` so insertion order is preserved and diffs stay readable).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(rows, sort_keys=False, default_flow_style=False)
    # NamedTemporaryFile(dir=...) so the temp lives on the same filesystem as
    # the target (cross-device rename is non-atomic). delete=False so we can
    # fsync + close + replace explicitly. noqa SIM115: a `with` block would
    # auto-close+delete the temp before we can fsync + atomic-replace it.
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        dir=path.parent, delete=False, mode="w", suffix=".tmp"
    )
    try:
        tmp.write(payload)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        # Clean up the orphaned temp file on any failure, then re-raise.
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)
        raise


def _load_raw_rows(path: Path) -> list[dict]:
    """Load a corpus file as raw rows, preserving ALL entries (incl. fixed).

    Unlike :func:`load_corpus` (which filters to open/pinned for the plugin's
    quarantine set), the mutation API must round-trip every row or promoting one
    entry would silently delete the others. Returns ``[]`` for a missing or
    empty file. Raises :class:`CorpusError` for a *present* file that is
    malformed (unparseable YAML or a non-list top level) so the mutation path
    never silently overwrites a corrupt-but-recoverable corpus with a single
    fresh row — ``add_entry`` on a hand-edited-but-broken ``known-failures.yaml``
    must fail loud, not destroy the original.
    """
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise CorpusError(f"malformed YAML in {path}: {e}") from e
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CorpusError(
            f"expected a top-level YAML list in {path}, got {type(raw).__name__}"
        )
    # Fail loud on non-dict rows (e.g. a bare string element): silently stripping
    # them contradicts the fail-loud-on-corrupt behavior shipped for malformed
    # YAML. A list containing a non-dict element is corruption, not a filter case.
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            raise CorpusError(
                f"row #{i} in {path} is not a mapping (got {type(r).__name__})"
            )
    return list(raw)


def add_entry(path, entry: CorpusEntry) -> CorpusEntry:
    """Append ``entry`` to the corpus at ``path`` and persist it.

    The entry is written verbatim (all ``CorpusEntry`` fields) so a subsequent
    :func:`load_corpus` reloads it with identical fields — the round-trip is the
    acceptance test. Creates the parent directory if needed so a fresh
    ``tests/`` dir works. Returns the entry unchanged (caller convenience).

    Raises :class:`CorpusError` if ``entry.status`` is not ``open`` or
    ``pinned`` — the shared invariant the CLI (``--status choices=[open,pinned]``)
    and :func:`load_corpus` (which drops anything else) both already enforce.
    Validating at this chokepoint means an MCP caller passing ``status='fixed'``
    gets a loud error instead of writing a row that is invisible on reload.
    """
    if entry.status not in ("open", "pinned"):
        raise CorpusError(
            f"invalid status {entry.status!r}: add_entry accepts only 'open' or "
            f"'pinned' (use promote_entry to flip to 'fixed')"
        )
    # Validate the id charset so quarantine_tests_for's ``test_quarantine__{id}``
    # is always a valid python identifier (spaces/dots/slashes/leading-digits are
    # not survivable by ``-`` -> ``_`` substitution alone).
    if not _SAFE_ID_RE.match(entry.id):
        raise CorpusError(
            f"invalid id {entry.id!r}: must match {_SAFE_ID_RE.pattern} "
            f"(pytest-safe identifier; quarantine test names are derived from it)"
        )
    p = Path(path)
    rows = _load_raw_rows(p)
    # Reject duplicate ids: a second row with an existing id creates duplicate
    # pytest test names and zombie pins (promote matches only the first).
    for row in rows:
        if row.get("id") == entry.id:
            raise CorpusError(
                f"duplicate id {entry.id!r}: an entry with this id already exists "
                f"in {p}"
            )
    # Derive the row from the dataclass so a new CorpusEntry field can never be
    # silently dropped on write (round-trip break). Hand-building a 6-key dict
    # would drift if CorpusEntry gains a field.
    rows.append(dataclasses.asdict(entry))
    _dump_corpus(p, rows)
    return entry


def promote_entry(path, entry_id: str, *, passes: bool) -> CorpusEntry:
    """Flip a corpus entry's status to ``fixed`` after a green re-run.

    Per PLAYBOOK: promotion is the ONLY path from ``pinned``/``open`` →
    ``fixed``, and ONLY after a deterministic green re-run. ``passes`` is that
    green signal:

    * ``passes=True``  — the repro now passes; set ``status: fixed``. The entry
      then drops out of :func:`load_corpus`'s active quarantine set (which only
      collects open/pinned), so no separate "delete xfail pin" step is needed.
    * ``passes=False`` — the repro still fails; promotion would be fraud, so
      this is a no-op (status unchanged, entry returned as-is).

    Raises :class:`CorpusError` if the corpus file is missing or ``entry_id``
    is not found — a missing id is a real caller bug, not something to swallow.
    Promoting an already-fixed entry is idempotent (returns it unchanged).
    """
    p = Path(path)
    rows = _load_raw_rows(p)
    if not p.exists():
        raise CorpusError(f"corpus file not found: {p}")
    target: dict | None = None
    for row in rows:
        if row.get("id") == entry_id:
            target = row
            break
    if target is None:
        raise CorpusError(
            f"entry id {entry_id!r} not found in corpus {p}"
        )
    if passes:
        target["status"] = "fixed"
        _dump_corpus(p, rows)
    return CorpusEntry(
        id=target["id"],
        invariant=target.get("invariant", ""),
        discovered_at=target.get("discovered_at", ""),
        source=target.get("source", ""),
        repro=target.get("repro", ""),
        status=target["status"],
    )


def quarantine_tests_for(entries):
    """Build the list of ``(test_name, repro_callable, status)`` tuples.

    ``test_name`` is a pytest-safe identifier derived from the entry id
    (``-`` -> ``_``). The repro callable is loaded eagerly so a missing or
    malformed repro surfaces at collection time rather than mid-run.

    A single broken repro (missing file, ``AttributeError`` for no ``repro``
    attribute, ``SyntaxError`` in the module) does NOT abort collection of the
    other quarantine items: that entry is skipped and a warning is written to
    stderr naming the id + reason. This honors the corpus.py docstring promise
    that "a broken corpus degrades to a skipped quarantine set instead of
    aborting the whole run."
    """
    tests = []
    for e in entries:
        try:
            repro = _load_repro(e.repro)
        except Exception as ex:  # any load failure skips this entry
            sys.stderr.write(
                f"testvibe: skipping quarantine entry {e.id!r}: "
                f"could not load repro {e.repro!r}: {ex}\n"
            )
            continue
        tests.append((f"test_quarantine__{e.id.replace('-', '_')}", repro, e.status))
    return tests
