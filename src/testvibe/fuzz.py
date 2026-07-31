"""testvibe.fuzz — S7 stateful fuzzer base.

``TestvibeStateMachine`` is a thin base over Hypothesis's
``RuleBasedStateMachine``; tools subclass it with ``@rule``/``@invariant``
methods describing their state space. ``run_fuzz`` runs the state machine as a
self-test and reports whether a violation (an invariant break) was found.
"""
from __future__ import annotations

import io
import sys
from typing import Type

from hypothesis import HealthCheck, settings
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test

__all__ = ["TestvibeStateMachine", "run_fuzz"]


class TestvibeStateMachine(RuleBasedStateMachine):
    """Base class for testvibe S7 stateful fuzz models.

    Subclass and define ``@rule`` methods (state transitions) and
    ``@invariant`` methods (properties that must always hold). ``run_fuzz``
    will search for a sequence of rules that breaks an invariant.
    """

    # pytest otherwise tries to collect this as a test class purely because of
    # the ``Test`` name prefix. Hypothesis' stateful runner does not use this
    # flag, so marking it is the conventional, safe way to stay quiet.
    __test__ = False


def run_fuzz(
    model_cls: Type[RuleBasedStateMachine],
    *,
    max_examples: int,
    step_count: int,
) -> bool:
    """Run *model_cls* as a Hypothesis state-machine test.

    Returns ``True`` if a violation was found (Hypothesis raised), ``False`` if
    the model satisfied its invariants across the whole search.

    A stdin shim is installed so Hypothesis never blocks trying to read the
    console; deadline/health-check suppressors make the run deterministic and
    CI-friendly.
    """
    fuzz_settings = settings(
        max_examples=max_examples,
        stateful_step_count=step_count,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    # Shim stdin so Hypothesis can never block on a console read.
    old_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        run_state_machine_as_test(model_cls, settings=fuzz_settings)
        return False
    except Exception:
        # An invariant was broken -> a violation was found.
        return True
    finally:
        sys.stdin = old_stdin
