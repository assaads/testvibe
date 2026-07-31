"""Tests for testvibe.fuzz — TestvibeStateMachine + run_fuzz."""
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
