"""testvibe.advisory — S6 advisory analyzer (DATA ONLY — no LLM, no network).

Produces three kinds of *advisory* (non-blocking signal) from a run's data:

* ``slow_but_passing`` — an operation whose p90 exceeds the baseline yet still
  passed. Worth optimizing, but not a regression.
* ``smell``            — a transcript line that looks like a deprecation /
  TODO / FIXME / HACK. Worth a look by the coding agent.
* ``coverage_gap``     — a path touched by dogfood/canary traces but absent
  from the fixture set. The agent turns these into new scenarios.

Testvibe makes **zero** AI/network calls here. The coding agent (via the MCP
server or the autopilot skill) interprets these rows. ``analyze`` imports no
network module and never opens a socket.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

__all__ = ["Advisory", "analyze"]

# Transcript lines that smell like tech debt / deprecation. Word-bounded so
# ordinary prose containing "fix" or "to do" is not flagged.
_SMELL_RE = re.compile(r"\b(deprecat(?:ed|ion)?|TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)


@dataclass
class Advisory:
    """A single non-blocking advisory signal.

    Attributes:
        kind:    one of ``slow_but_passing`` | ``smell`` | ``coverage_gap``.
        message: human-readable one-line summary.
        detail:  structured/machine-friendly detail (op name, path, etc.).
    """

    kind: str
    message: str
    detail: str = ""


def _field(obj: Any, key: str) -> Any:
    """Read ``key`` from ``obj`` whether it is a dict or an attribute object."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def analyze(
    report: Iterable[Any],
    baseline: Any,
    fixture_paths: Iterable[str],
    touched_paths: Iterable[str],
    transcript: str,
) -> list[Advisory]:
    """Analyze run data and return advisory rows.

    Parameters:
        report:        iterable of op records (dict or object) each exposing a
                       ``name``, ``p90_ms`` (numeric), and ``passed`` (bool).
        baseline:      p90 baseline in ms; ops with ``p90_ms > baseline`` that
                       passed are ``slow_but_passing``. ``None`` disables this
                       check.
        fixture_paths: paths covered by existing fixtures.
        touched_paths: paths touched by dogfood/canary traces.
        transcript:    raw transcript text to scan for smell lines.

    Returns a list of :class:`Advisory`. Performs no LLM and no network call.
    """
    advisories: list[Advisory] = []

    # slow_but_passing: op whose p90 exceeds baseline but that passed.
    for op in report:
        name = _field(op, "name")
        p90 = _field(op, "p90_ms")
        passed = _field(op, "passed")
        if passed and baseline is not None and p90 is not None and p90 > baseline:
            advisories.append(
                Advisory(
                    kind="slow_but_passing",
                    message=f"{name} p90 {p90}ms exceeds baseline {baseline}ms but passed",
                    detail=f"op={name} p90_ms={p90} baseline_ms={baseline}",
                )
            )

    # smell: deprecation/TODO/FIXME-style lines in the transcript.
    if transcript:
        for line in transcript.splitlines():
            if _SMELL_RE.search(line):
                advisories.append(
                    Advisory(
                        kind="smell",
                        message=line.strip(),
                        detail="transcript smell line",
                    )
                )

    # coverage_gap: paths touched but absent from fixtures.
    fixture_set = set(fixture_paths or [])
    for path in touched_paths or []:
        if path not in fixture_set:
            advisories.append(
                Advisory(
                    kind="coverage_gap",
                    message=f"{path} touched but absent from fixtures",
                    detail=f"touched_path={path}",
                )
            )

    return advisories
