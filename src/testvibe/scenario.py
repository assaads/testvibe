"""Scenario + invariant decorators (Task A2).

``@scenario(name, *, kind, surfaces)`` tags a pytest test as a testvibe
scenario and registers it. The decorator preserves the function for normal
pytest collection — the only mutations are metadata (``__testvibe__``) and a
kind-based skip when ``kind != "hermetic"`` (canary/dogfood scenarios are run
via the scheduler/MCP, not during a default local pytest run).

``@invariant(name)`` registers an invariant check callable.
"""

from __future__ import annotations

from typing import Callable

# Registries populated by the decorators. Other goals (report/CI) may read
# these to enumerate known scenarios/invariants.
SCENARIOS: dict[str, dict] = {}
INVARIANTS: dict[str, Callable] = {}


def scenario(
    name: str,
    *,
    kind: str = "hermetic",
    surfaces=("invariant", "perf", "advisory"),
):
    """Tag a pytest test as a testvibe scenario.

    Parameters
    ----------
    name:
        Human-readable scenario id; used as the registry key.
    kind:
        ``"hermetic"`` (default — runs in any pytest invocation),
        ``"canary"`` or ``"dogfood"`` (skipped locally, run via scheduler/MCP).
    surfaces:
        Which output surfaces this scenario contributes to.

    The decorated function is returned (possibly skip-marked) and remains
    collectable by pytest as a normal test.
    """
    import pytest

    def deco(fn: Callable) -> Callable:
        fn = pytest.mark.testvibe_scenario(fn)
        fn.__testvibe__ = {"name": name, "kind": kind, "surfaces": tuple(surfaces)}
        SCENARIOS[name] = {"fn": fn, "kind": kind, "surfaces": tuple(surfaces)}
        if kind != "hermetic":
            fn = pytest.mark.skip(reason=f"{kind} scenario; run via scheduler/MCP")(fn)
        return fn

    return deco


def invariant(name: str):
    """Register an invariant check asserted alongside scenarios by the plugin."""

    def deco(fn: Callable) -> Callable:
        INVARIANTS[name] = fn
        fn.__testvibe_invariant__ = name
        return fn

    return deco
