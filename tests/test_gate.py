"""S0 gate helpers — ``scrub_env`` + the reusable composite action contract.

Task A6. ``scrub_env`` drops tool-specific env vars by prefix so the CI gate
matches CI reality rather than the dev shell (the SYNCESTRA_* leak class). The
composite action wraps the gate steps (uv/ruff/mypy/pytest) for reuse.
"""

import os
import pathlib

import yaml


# --------------------------------------------------------------------------- #
# scrub_env
# --------------------------------------------------------------------------- #
def test_scrub_env_drops_only_prefixed_keys():
    from testvibe.gate import scrub_env

    result = scrub_env("X_", {"X_A": 1, "Y": 2})
    assert result == {"Y": 2}


def test_scrub_env_drops_all_matching_prefix():
    from testvibe.gate import scrub_env

    result = scrub_env("SYNCESTRA_", {
        "SYNCESTRA_E2E_TOKEN": "tok",
        "SYNCESTRA_E2E_REMOTE": "r",
        "PATH": "/usr/bin",
        "HOME": "/h",
    })
    assert result == {"PATH": "/usr/bin", "HOME": "/h"}


def test_scrub_env_returns_new_dict_does_not_mutate_input():
    from testvibe.gate import scrub_env

    original = {"X_A": 1, "Y": 2}
    result = scrub_env("X_", original)
    assert result is not original                       # new dict
    assert original == {"X_A": 1, "Y": 2}               # input untouched


def test_scrub_env_empty_when_all_match_prefix():
    from testvibe.gate import scrub_env

    assert scrub_env("SECRET_", {"SECRET_A": 1, "SECRET_B": 2}) == {}


def test_scrub_env_keeps_everything_when_none_match():
    from testvibe.gate import scrub_env

    env = {"A": "1", "B": "2"}
    assert scrub_env("ZZZ_", env) == env


def test_scrub_env_default_env_is_os_environ_copy(monkeypatch):
    """With env=None, scrub against a copy of os.environ."""
    from testvibe.gate import scrub_env

    monkeypatch.setenv("TVTEST_PREFIXED", "leaked")
    monkeypatch.setenv("TVTEST_KEPT", "kept")
    result = scrub_env("TVTEST_PREFIX")
    assert "TVTEST_PREFIXED" not in result
    assert result["TVTEST_KEPT"] == "kept"
    # must NOT be the live os.environ object (a copy)
    assert result is not os.environ


# --------------------------------------------------------------------------- #
# composite action contract
# --------------------------------------------------------------------------- #
def _action_path() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / ".github" / "actions" / "testvibe-gate" / "action.yml"


def test_composite_action_yaml_parses_and_is_composite():
    p = _action_path()
    assert p.is_file(), f"composite action missing at {p}"
    data = yaml.safe_load(p.read_text())
    assert data["name"], "action must declare a name"
    assert data.get("runs", {}).get("using") == "composite"


def test_composite_action_declares_scrub_env_input():
    data = yaml.safe_load(_action_path().read_text())
    inputs = data.get("inputs", {})
    assert "scrub-env" in inputs, "action must declare a 'scrub-env' string input"
    assert inputs["scrub-env"].get("type") == "string"


def test_composite_action_runs_the_gate_steps():
    data = yaml.safe_load(_action_path().read_text())
    steps = data["runs"]["steps"]

    # Concatenate run/shell bodies so we can assert on the commands issued.
    bodies = []
    for step in steps:
        run = step.get("run")
        if run:
            bodies.append(run)
    blob = "\n".join(bodies)

    # The S0 gate runs: uv sync --extra dev, ruff, mypy, pytest (hermetic subset,
    # benchmark disabled), with the scrub-env prefix expanded into the env.
    assert "uv sync --extra dev" in blob
    assert "ruff check ." in blob
    assert "mypy" in blob
    assert "pytest" in blob
    assert "--benchmark-disable" in blob
    assert 'not live and not dogfood' in blob
    # the scrub-env input must actually be wired into the test step
    assert "scrub-env" in blob or "TESTVIBE_SCRUB_ENV" in blob
