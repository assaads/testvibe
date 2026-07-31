"""pytest plugin (auto-activated via the ``pytest11`` entry point).

Foundation stub (Task A1): registers the testvibe marker set so scenarios can
be tagged and selected. The real plugin machinery (scenario collection, perf
telemetry, advisory capture, quarantine emission) is added in later goals
(A2/A4) — this stub only proves the plugin loads and markers are visible to
pytest.
"""

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
