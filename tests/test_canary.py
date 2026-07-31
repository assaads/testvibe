"""Tests for testvibe.canary — rate-limit backoff + scratch lifecycle (S3)."""

import pytest

from testvibe.canary import Persistent, Transient, scratch_lifecycle, with_backoff
from testvibe.report import Failure

# --- with_backoff: transient is retried, eventually succeeds (not product) ---


def test_backoff_retries_transient_then_succeeds(monkeypatch):
    """A fake boundary returning 403 twice then 200 is retried and succeeds.

    The 403 (rate-limit) is a TRANSIENT/infra signal, NOT a product failure.
    A successful retry is not a product failure.
    """
    sleeps = []
    monkeypatch.setattr("testvibe.canary.time.sleep", lambda d: sleeps.append(d))

    calls = {"n": 0}

    def op():
        calls["n"] += 1
        if calls["n"] < 3:  # first two attempts: rate-limited (transient)
            raise Transient("403 rate-limited")
        return "200 OK"

    result = with_backoff(op, retries=5, base=0.01)

    assert result == "200 OK"  # success, not a Failure
    assert calls["n"] == 3  # retried twice
    # exponential backoff schedule: base*2**0, base*2**1, ...
    assert sleeps == [0.01 * 2**0, 0.01 * 2**1]
    assert not isinstance(result, Failure)


def test_backoff_exponential_schedule(monkeypatch):
    """Backoff must be exponential: base * 2**attempt for each retry."""
    sleeps = []
    monkeypatch.setattr("testvibe.canary.time.sleep", lambda d: sleeps.append(d))

    def op():
        raise Transient("always transient")

    result = with_backoff(op, retries=3, base=0.002)
    # 3 retries -> 3 sleeps with base*2**0, base*2**1, base*2**2
    assert sleeps == [0.002, 0.004, 0.008]
    # exhausted transient retries -> infra failure (flaky boundary), not product
    assert isinstance(result, Failure)
    assert result.kind == "infra"


def test_backoff_persistent_is_product_failure():
    """A PERSISTENT error (e.g. 401/403 permission) is a product failure."""

    def op():
        raise Persistent("401 unauthorized")

    result = with_backoff(op, retries=5, base=0.001)
    assert isinstance(result, Failure)
    assert result.kind == "product"


def test_backoff_persistent_raises_immediately_no_retries(monkeypatch):
    """Persistent errors short-circuit: no retries, no backoff sleeps."""
    sleeps = []
    monkeypatch.setattr("testvibe.canary.time.sleep", lambda d: sleeps.append(d))

    calls = {"n": 0}

    def op():
        calls["n"] += 1
        raise Persistent("permission denied")

    result = with_backoff(op, retries=5, base=0.01)
    assert isinstance(result, Failure)
    assert result.kind == "product"
    assert calls["n"] == 1  # never retried
    assert sleeps == []  # no backoff


def test_backoff_success_first_try_no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("testvibe.canary.time.sleep", lambda d: sleeps.append(d))

    def op():
        return "ok"

    result = with_backoff(op, retries=3, base=0.01)
    assert result == "ok"
    assert sleeps == []


# --- scratch_lifecycle: setup on entry, teardown always on exit ---


def test_scratch_lifecycle_setup_and_teardown():
    log = []
    resource = {"id": "scratch-1"}

    def setup():
        log.append("setup")
        return resource

    def teardown(res):
        log.append(("teardown", res))

    with scratch_lifecycle(setup, teardown) as res:
        log.append(("use", res))
        assert res is resource

    assert log == ["setup", ("use", resource), ("teardown", resource)]


def test_scratch_lifecycle_teardown_runs_on_error():
    """teardown(resource) must run even when the body raises."""
    log = []
    resource = {"id": "scratch-2"}

    def setup():
        return resource

    def teardown(res):
        log.append(("teardown", res))

    with pytest.raises(RuntimeError, match="boom"), scratch_lifecycle(setup, teardown):
        raise RuntimeError("boom")

    assert log == [("teardown", resource)]


def test_scratch_lifecycle_yields_resource():
    def setup():
        return "the-resource"

    def teardown(res):
        pass

    with scratch_lifecycle(setup, teardown) as res:
        assert res == "the-resource"
