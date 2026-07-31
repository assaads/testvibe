"""Shared conftest for the self-dogfood ``scenarios/`` suite.

Two responsibilities:

1. **Isolation guard** — a session-autouse fixture that proves no
   ``known-failures.yaml`` ever leaks onto a repo-collected path. The plugin's
   ``pytest_collect_file`` collects ANY file of that exact name pytest walks, so
   the dogfood suite must keep every corpus artifact under ``tmp_path``. The
   guard asserts absence under ``scenarios/`` and the repo root at session start
   and end; if a scenario ever materializes one, the suite fails loud rather
   than silently polluting the default gate.
2. **Collection hook** — defensively rejects a ``known-failures.yaml`` walked
   under ``scenarios/`` so the plugin never turns a dogfood artifact into stray
   quarantine items.

The plugin's ``env`` fixture (auto-registered via the ``pytest11`` entry point)
is available to every scenario unmodified; this conftest does not shadow it.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCENARIOS_DIR = Path(__file__).resolve().parent
_FORBIDDEN_NAME = "known-failures.yaml"


def _no_corpus_leak(where: str) -> None:
    """Assert no ``known-failures.yaml`` exists under scenarios/ or repo root."""
    leaked: list[Path] = []
    # Anywhere under scenarios/ (recursive).
    leaked.extend(p for p in _SCENARIOS_DIR.rglob(_FORBIDDEN_NAME))
    # Directly at the repo root.
    root_file = _REPO_ROOT / _FORBIDDEN_NAME
    if root_file.exists():
        leaked.append(root_file)
    assert not leaked, (
        f"{where}: known-failures.yaml leaked onto repo-collected path(s): "
        f"{leaked} — the plugin would collect these globally"
    )


@pytest.fixture(autouse=True, scope="session")
def _isolation_guard() -> Generator[None, None, None]:
    """Assert no corpus file leaks at session start and end."""
    _no_corpus_leak("session start")
    yield
    _no_corpus_leak("session end")


def pytest_collect_file(file_path: Path, parent):  # type: ignore[no-untyped-def]
    """Reject a ``known-failures.yaml`` walked under scenarios/.

    The plugin's own ``pytest_collect_file`` already collects these globally; if
    one ever appears under ``scenarios/`` the isolation guard above catches it,
    but this hook makes the failure a collection-time error with a clear message
    rather than silent quarantine collection.
    """
    if file_path.name == _FORBIDDEN_NAME and _SCENARIOS_DIR in file_path.parents:
        pytest.fail(
            f"isolation violation: {_FORBIDDEN_NAME} materialized under "
            f"scenarios/ at {file_path}",
            pytrace=False,
        )
    return None
