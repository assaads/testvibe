"""Tests for the @scenario/@invariant API and the plugin's env fixture (Task A2).

These verify:
  * a ``@scenario`` function is collected as a normal pytest test,
  * the decorator registers the scenario in ``SCENARIOS`` and attaches
    ``__testvibe__`` metadata without breaking collection,
  * a non-hermetic scenario is marked skip (run via scheduler/MCP),
  * the ``env`` fixture provides a hermetic scratch workspace.
"""

import pathlib
import subprocess
import sys
import textwrap


# ---------------------------------------------------------------------------
# Subprocess-driven: real pytest collection of a @scenario function.
# ---------------------------------------------------------------------------
def test_scenario_is_collected_as_test(tmp_path: pathlib.Path):
    (tmp_path / "test_demo.py").write_text(textwrap.dedent("""
        from testvibe import scenario
        @scenario("push_pull_roundtrip")
        def test_push_pull(env):
            assert True
    """))
    (tmp_path / "conftest.py").write_text("import testvibe.plugin  # activate\n")
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "--collect-only", "-q"],
        capture_output=True, text=True, check=True,
    )
    assert "test_push_pull" in out.stdout


# ---------------------------------------------------------------------------
# Unit-level: decorator registers + tags + skips, preserves the function.
# ---------------------------------------------------------------------------
def test_scenario_registers_and_tags_metadata():
    from testvibe import scenario
    from testvibe.scenario import SCENARIOS

    @scenario("unit_demo")
    def test_x():  # local; pytest won't collect it
        return True

    # function preserved (callable, returns expected value)
    assert test_x() is True
    # metadata attached
    assert test_x.__testvibe__ == {
        "name": "unit_demo",
        "kind": "hermetic",
        "surfaces": ("invariant", "perf", "advisory"),
    }
    # registry populated
    assert "unit_demo" in SCENARIOS
    assert SCENARIOS["unit_demo"]["kind"] == "hermetic"
    assert SCENARIOS["unit_demo"]["surfaces"] == ("invariant", "perf", "advisory")
    # tagged with the testvibe_scenario marker
    mark_names = {m.name for m in getattr(test_x, "pytestmark", [])}
    assert "testvibe_scenario" in mark_names


def test_non_hermetic_scenario_is_marked_skip():
    from testvibe import scenario

    @scenario("canary_demo", kind="canary")
    def test_y():
        return True

    # function still callable / preserved
    assert test_y() is True
    mark_names = {m.name for m in getattr(test_y, "pytestmark", [])}
    assert "skip" in mark_names
    # the hermetic marker is still present too
    assert "testvibe_scenario" in mark_names


def test_invariant_registers_and_tags():
    from testvibe import invariant
    from testvibe.scenario import INVARIANTS

    @invariant("inv_demo")
    def my_check():
        return True

    assert INVARIANTS["inv_demo"] is my_check
    assert my_check.__testvibe_invariant__ == "inv_demo"
    assert my_check() is True


# ---------------------------------------------------------------------------
# env fixture end-to-end via subprocess.
# ---------------------------------------------------------------------------
def test_env_fixture_provides_hermetic_workspace(tmp_path: pathlib.Path):
    (tmp_path / "test_env_demo.py").write_text(textwrap.dedent("""
        from testvibe import scenario

        @scenario("env_roundtrip")
        def test_env_roundtrip(env):
            env.write("nested/dir/file.txt", "hello")
            assert env.read("nested/dir/file.txt") == "hello"
            assert env.root.exists()
    """))
    out = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path), "-q"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert "1 passed" in out.stdout
