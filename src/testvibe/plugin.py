"""pytest plugin (auto-activated via the ``pytest11`` entry point).

Registers the testvibe marker set (Task A1), provides the hermetic ``env``
fixture (Task A2), and auto-collects a ``known-failures.yaml`` corpus as
quarantined xfail-strict tests (Task A4).
"""

# stdlib ``warnings`` is used (rather than pytest's PytestWarning) so the
# collection hook can emit a visible, capturable warning without depending on
# pytest internals. Pytest surfaces these in its warning summary.
import warnings

import pytest

# Marker names every testvibe scenario/annotation may carry. Centralized so
# later goals can grow the set without touching call sites.
MARKERS = (
    "testvibe_scenario",
    "property",
    "perf",
    "live",
    "dogfood",
    "quarantine",
)


def pytest_configure(config):
    """Register testvibe markers with pytest so they are not reported as unknown."""
    for name in MARKERS:
        config.addinivalue_line("markers", f"{name}: testvibe marker")


# ---------------------------------------------------------------------------
# Task A2 — the hermetic ``env`` fixture scenarios may request.
# ---------------------------------------------------------------------------
@pytest.fixture
def env(tmp_path):
    """Hermetic scratch workspace scenarios may request.

    Exposes ``.root`` (a ``pathlib.Path`` under pytest's tmp_path), ``.write``
    and ``.read`` for relative paths inside the workspace.
    """

    class Env:
        def __init__(self, root):
            self.root = root

        def write(self, rel, data):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(data)

        def read(self, rel):
            return (self.root / rel).read_text()

    return Env(tmp_path)


# ---------------------------------------------------------------------------
# Task A4 — auto-collect a known-failures.yaml corpus as quarantined tests.
# ---------------------------------------------------------------------------
class _QuarantineItem(pytest.Item):
    """One ``xfail(strict=True)`` test that re-runs a captured failure's repro.

    A still-failing repro -> xfail (expected, quiet). A now-passing repro ->
    XPASS -> under ``strict=True`` this is a failure, which is the CI promotion
    signal (``testvibe corpus promote <id>``).
    """

    def __init__(self, *, name, parent, repro_fn, entry_id):
        super().__init__(name, parent)
        self._repro_fn = repro_fn
        self._entry_id = entry_id
        self.add_marker(pytest.mark.quarantine)
        self.add_marker(pytest.mark.xfail(strict=True, reason=entry_id, run=True))

    def runtest(self):
        self._repro_fn()

    def reportinfo(self):
        return self.path, 0, f"quarantine::{self._entry_id}"


class _KnownFailuresFile(pytest.File):
    """Collector that turns one ``known-failures.yaml`` into quarantine items."""

    def collect(self):
        # Imported lazily so the plugin module never fails to import if the
        # corpus module has an unmet dependency in some other environment.
        from testvibe.corpus import CorpusError, load_corpus, quarantine_tests_for

        try:
            entries = load_corpus(self.path)
        except CorpusError as e:
            # A malformed known-failures.yaml must NOT abort the whole pytest
            # run — warn and skip the quarantine items for this file only.
            warnings.warn(
                f"testvibe: skipping malformed known-failures corpus at "
                f"{self.path}: {e}",
                stacklevel=2,
            )
            return

        for test_name, repro_fn, _status in quarantine_tests_for(entries):
            yield _QuarantineItem.from_parent(
                self, name=test_name, repro_fn=repro_fn, entry_id=test_name
            )


def pytest_collect_file(file_path, parent):
    """When pytest stumbles on a ``known-failures.yaml``, collect its repros."""
    if file_path.name == "known-failures.yaml":
        return _KnownFailuresFile.from_parent(parent, path=file_path)
    return None
