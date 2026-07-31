"""S1 self-dogfood scenario: init scaffold round-trip.

Drives ``testvibe.scaffold.generate`` the way a user drives ``testvibe init``:
hand it a contract name, expect the four canonical surfaces written under a
tmp dest, each tagged with the testvibe generation header, and the boundary
template a pytest-collectable Python module.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from testvibe import scaffold, scenario

_EXPECTED_FILES = (
    "test_s1_boundary.py",
    "test_s2_property.py",
    "known-failures.yaml",
    "conftest.py",
)


@scenario("s1_init_scaffold_roundtrip", kind="hermetic")
def test_s1_init_scaffold_roundtrip(tmp_path: Path) -> None:
    dest = tmp_path / "scaffolded"
    scaffold.generate("my-tool", dest)

    # All four canonical surfaces are present, and ONLY those four.
    actual = {p.name for p in dest.iterdir()}
    assert actual == set(_EXPECTED_FILES), (
        f"generate did not write the expected 4 surfaces: got {sorted(actual)}"
    )

    # Every written file carries the testvibe generation + contract markers.
    for name in _EXPECTED_FILES:
        text = (dest / name).read_text(encoding="utf-8")
        assert "# testvibe:generated" in text, f"{name} missing # testvibe:generated header"
        assert "# testvibe:contract: my-tool" in text, (
            f"{name} missing # testvibe:contract header"
        )

    # The boundary template is a pytest-collectable Python module: it must
    # import cleanly (no syntax error, no missing imports) so pytest can walk it
    # even before the user fills in the TODO keep blocks.
    boundary = dest / "test_s1_boundary.py"
    spec = importlib.util.spec_from_file_location("tv_s1_boundary", boundary)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # must not raise

    # Idempotent: re-generating yields byte-identical output for ALL four
    # surfaces (a user re-running init must not see spurious diffs on any file).
    first_run = {
        name: (dest / name).read_text(encoding="utf-8") for name in _EXPECTED_FILES
    }
    scaffold.generate("my-tool", dest)
    for name in _EXPECTED_FILES:
        second = (dest / name).read_text(encoding="utf-8")
        assert first_run[name] == second, (
            f"generate is not idempotent: {name} differs across repeated calls"
        )
