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


def load_corpus(path) -> list[CorpusEntry]:
    """Load a ``known-failures.yaml`` corpus, keeping only open/pinned entries.

    Returns ``[]`` when the file is missing or empty — so callers (and the
    plugin's collection hook) never have to special-case absence.
    """
    p = Path(path)
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or []
    return [
        CorpusEntry(**e) for e in raw if e.get("status") in ("open", "pinned")
    ]


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
