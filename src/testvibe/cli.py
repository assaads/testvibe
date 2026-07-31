"""``testvibe`` console-script entry point (foundation stub).

The real CLI (``init``, ``upgrade``, ``run``, ``corpus`` …) is owned by a later
scaffold/cli goal. A no-op ``main`` exists here only so the
``[project.scripts] testvibe = "testvibe.cli:main"`` entry point in
``pyproject.toml`` resolves at install time and ``testvibe`` on the PATH does
not crash with ``ImportError``. Replaced wholesale by the real CLI later.
"""


def main() -> int:
    """Placeholder entry point — prints a notice and exits cleanly."""
    raise SystemExit(0)
