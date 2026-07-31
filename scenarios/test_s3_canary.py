"""S3 self-dogfood scenario: canary skip-mark + backoff transient/persistent split.

Two user-facing behaviors of the canary surface:

1. ``@scenario(kind="canary")`` registers the scenario AND skip-marks it so a
   bare ``pytest scenarios/`` collects but never runs it (canaries touch real
   external boundaries and run via the scheduler/MCP, not a default local run).
   The ``@scenario``-decorated function below therefore only asserts
   skip-semantics (it is *itself* the skip-marked canary — running its body
   locally would defeat the point).
2. ``canary.with_backoff`` honors the two sentinel exceptions exactly. Because
   the canary body is skipped, ``with_backoff`` is exercised in a separate,
   always-run plain test (``test_s3_backoff_*``) so its assertions always run.
"""

from __future__ import annotations

from testvibe import scenario
from testvibe.canary import Persistent, Transient, with_backoff
from testvibe.report import Failure
from testvibe.scenario import SCENARIOS


@scenario("s3_canary_skip_and_backoff", kind="canary")
def test_s3_canary_skip_and_backoff() -> None:
    """Canary body: collected+skipped locally. Only its skip-semantics matter.

    A canary touching a real boundary would live here; locally this function
    must be skipped, so its body is intentionally trivial. The
    skip-mark itself is asserted by ``test_s3_canary_is_skip_marked`` below.
    """
    # If this body ever runs under a default `pytest scenarios/`, the skip-mark
    # regressed — fail loud to surface it.
    raise AssertionError("canary body ran locally — skip-mark regressed")


def test_s3_canary_is_skip_marked() -> None:
    """The registered canary scenario is collected but skip-marked (skip-semantics)."""
    fn = SCENARIOS["s3_canary_skip_and_backoff"]["fn"]
    assert fn.__testvibe__["kind"] == "canary"
    # The decorator wraps with pytest.mark.skip; its presence is what keeps a
    # default `pytest scenarios/` from executing canaries against real boundaries.
    has_skip_mark = any(
        getattr(mark, "name", None) == "skip"
        for mark in getattr(fn, "pytestmark", [])
    )
    assert has_skip_mark, "canary scenario was not skip-marked"


def test_s3_backoff_persistent_is_product_no_retry() -> None:
    """Persistent boundary failure -> product Failure, never retried."""
    calls = {"n": 0}

    def persistent_op() -> None:
        calls["n"] += 1
        raise Persistent("403 forbidden")

    result = with_backoff(persistent_op, retries=3, base=0.0)
    assert isinstance(result, Failure)
    assert result.kind == "product", "persistent boundary must classify as product"
    # Persistent is non-retryable: the op runs exactly once.
    assert calls["n"] == 1, f"persistent op was retried {calls['n']} times (must be 1)"


def test_s3_backoff_transient_exhausted_is_infra() -> None:
    """Transient that exhausts retries -> infra Failure (boundary stayed down)."""
    calls = {"n": 0}

    def always_transient() -> None:
        calls["n"] += 1
        raise Transient("429 rate limited")

    result = with_backoff(always_transient, retries=2, base=0.0)
    assert isinstance(result, Failure)
    assert result.kind == "infra", "transient-exhausted boundary must classify as infra"
    # retries=2 means initial attempt + 2 retries = 3 total invocations.
    assert calls["n"] == 3, (
        f"transient op ran {calls['n']} times, expected 3 (1 + retries=2)"
    )


def test_s3_backoff_successful_retry_returns_op_result() -> None:
    """A successful retry returns the op's real result, NOT a Failure."""
    calls = {"n": 0}

    def transient_then_ok() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise Transient("blip")
        return "recovered"

    result = with_backoff(transient_then_ok, retries=3, base=0.0)
    assert result == "recovered", f"successful retry must return op result, got {result!r}"
    assert not isinstance(result, Failure), "a recovered op must NOT surface as a Failure"
    assert calls["n"] == 2
