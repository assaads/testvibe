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

import importlib.util
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
    for i, e in enumerate(raw):
        if not isinstance(e, dict):
            raise CorpusError(
                f"entry #{i} in {p} is not a mapping (got {type(e).__name__})"
            )
        # Filter by status BEFORE validating completeness, so legacy fixed /
        # ignored entries with missing fields don't poison the whole load.
        if e.get("status") not in ("open", "pinned"):
            continue
        missing = [f for f in _REQUIRED_FIELDS if f not in e]
        if missing:
            raise CorpusError(
                f"entry #{i} in {p} (id={e.get('id')!r}) missing fields: {missing}"
            )
        try:
            entries.append(CorpusEntry(**e))
        except TypeError as ex:
            raise CorpusError(f"entry #{i} in {p} (id={e.get('id')!r}) invalid: {ex}") from ex
    return entries


def _load_repro(repro_path):
    """Import ``repro_path`` from disk and return its ``repro`` callable."""
    rp = Path(repro_path)
    spec = importlib.util.spec_from_file_location(rp.stem, rp)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None  # for type-checkers; spec_from_file_location sets a loader
    spec.loader.exec_module(mod)
    return mod.repro


def quarantine_tests_for(entries):
    """Build the list of ``(test_name, repro_callable, status)`` tuples.

    ``test_name`` is a pytest-safe identifier derived from the entry id
    (``-`` -> ``_``). The repro callable is loaded eagerly so a missing or
    malformed repro surfaces at collection time rather than mid-run.
    """
    return [
        (f"test_quarantine__{e.id.replace('-', '_')}", _load_repro(e.repro), e.status)
        for e in entries
    ]
