"""Tests for testvibe.fuzz — TestvibeStateMachine + run_fuzz."""
import pytest
from hypothesis.stateful import invariant, rule

from testvibe.fuzz import TestvibeStateMachine, run_fuzz


class ToyModel(TestvibeStateMachine):
    def __init__(self):
        super().__init__()
        self.n = 0

    @invariant()
    def nonneg(self):
        assert self.n >= 0

    @rule()
    def dec(self):
        self.n -= 1


def test_fuzz_finds_seeded_violation():
    # A state machine with a seeded bug (dec below an invariant floor) must be
    # detected by run_fuzz, which returns True when a violation is found.
    assert run_fuzz(ToyModel, max_examples=10, step_count=5) is True


def test_fuzz_returns_false_on_clean_model():
    class CleanModel(TestvibeStateMachine):
        def __init__(self):
            super().__init__()
            self.n = 0

        @invariant()
        def nonneg(self):
            assert self.n >= 0

        @rule()
        def inc(self):
            self.n += 1

    assert run_fuzz(CleanModel, max_examples=10, step_count=5) is False


def test_fuzz_buggy_rule_is_not_reported_as_violation():
    # A bug INSIDE a @rule body (TypeError) is NOT an invariant break.
    # run_fuzz must surface it as a real error rather than swallow it as
    # "found violation" (True). Regression for the over-broad except clause.
    class BuggyRuleModel(TestvibeStateMachine):
        def __init__(self):
            super().__init__()
            self.n = 0

        @invariant()
        def nonneg(self):
            assert self.n >= 0

        @rule()
        def buggy(self):
            # A genuine bug in the rule body — NOT an assertion/invariant.
            return 1 + "x"  # TypeError: unsupported operand types

    # The bug must propagate (raise), and crucially must NOT be reported as an
    # invariant violation (AssertionError) nor returned as True.
    with pytest.raises(Exception) as exc_info:
        run_fuzz(BuggyRuleModel, max_examples=10, step_count=5)
    assert not isinstance(exc_info.value, AssertionError), (
        "buggy @rule was misreported as an invariant (AssertionError) violation"
    )
