"""``testvibe`` console-script entry point (foundation stub).

The real CLI (``init``, ``upgrade``, ``run``, ``corpus`` …) is owned by a later
scaffold/cli goal. A no-op ``main`` exists here only so the
``[project.scripts] testvibe = "testvibe.cli:main"`` entry point in
``pyproject.toml`` resolves at install time and ``testvibe`` on the PATH does
not crash with ``ImportError``. Replaced wholesale by the real CLI later.
"""
import sys


def main() -> int:
    """Minimal stub CLI. Real subcommands (init/upgrade/run/...) arrive with the scaffold goal."""
    sys.stderr.write("testvibe: CLI not implemented yet (stub).\n")
    return 0
