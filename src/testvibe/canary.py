"""testvibe.canary — S3 boundary helpers: rate-limit backoff + scratch lifecycle.

Canary scenarios (``@scenario(kind="canary")``) exercise real external
boundaries (GitHub, git, MCP servers). Two recurring needs are encapsulated
here:

* :func:`with_backoff` — retry a transiently-failing boundary operation with
  exponential backoff, and surface a product failure only when the *tool* (not
  the boundary) is at fault.
* :func:`scratch_lifecycle` — a context manager that provisions a scratch
  resource on entry and *always* tears it down on exit, even when the body
  raises.

Transient vs persistent signaling
---------------------------------
A boundary ``op`` signals retryability by raising one of two sentinel
exceptions:

* :class:`Transient` — the boundary is momentarily unavailable (HTTP 429 / 5xx,
  network blip, scrubbed env). This is an **infra**-class issue: retry with
  exponential backoff. If retries are eventually exhausted the boundary stayed
  down, which is still infra (a flaky environment), not a product regression.
* :class:`Persistent` — the operation cannot possibly succeed as posed (HTTP
  401/403 permission, malformed request). This is a **product** failure: the
  tool itself is misconfigured or broken.

A successful retry is *not* a product failure. ``with_backoff`` returns the
op's successful result directly; it returns a :class:`~testvibe.report.Failure`
only when the op gives up (persistent) or the boundary never recovers
(transient-exhausted → infra).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Generator
from typing import Any

from testvibe.report import Failure

__all__ = ["Persistent", "Transient", "scratch_lifecycle", "with_backoff"]


class Transient(Exception):
    """Raised by an op to request a retry (infra-class: rate limit, network)."""


class Persistent(Exception):
    """Raised by an op to signal a non-retryable product failure."""


def with_backoff(op: Callable[[], Any], *, retries: int, base: float) -> Any:
    """Call ``op()`` with exponential backoff on transient failures.

    On a :class:`Transient` error the op is retried up to ``retries`` more
    times, sleeping ``base * 2**attempt`` before retry ``attempt`` (0-indexed).
    On a :class:`Persistent` error the op is not retried.

    Returns the op's successful result, or a :class:`~testvibe.report.Failure`:

    * ``Failure(kind="product")`` — persistent error (the tool is at fault).
    * ``Failure(kind="infra")``   — transient errors exhausted all retries
      (the boundary stayed down; an environment/infra issue, not a product
      regression).
    """
    for attempt in range(retries + 1):
        try:
            return op()
        except Persistent as exc:
            # Non-retryable: the tool itself is broken/misconfigured.
            return Failure(
                kind="product",
                message=f"persistent boundary failure: {exc}",
                detail=f"{type(exc).__name__}: {exc}",
            )
        except Transient as exc:
            if attempt < retries:
                # Exponential backoff: base * 2**attempt before the next try.
                time.sleep(base * (2**attempt))
                continue
            # Retries exhausted — the boundary never recovered (infra).
            return Failure(
                kind="infra",
                message=f"transient boundary failure after {retries} retries: {exc}",
                detail=f"{type(exc).__name__}: {exc}",
            )
    # Unreachable: every loop iteration returns (the final Transient branch
    # above returns). Kept as a defensive guard for type-checkers.
    raise RuntimeError("with_backoff: unreachable")  # pragma: no cover


@contextlib.contextmanager
def scratch_lifecycle(
    setup: Callable[[], Any], teardown: Callable[[Any], None]
) -> Generator[Any, None, None]:
    """Provision a scratch resource on entry; always tear it down on exit.

    ``setup()`` runs on entry and its return value becomes the yielded
    resource. ``teardown(resource)`` runs on exit — including when the body
    raises — so scratch state is never leaked.
    """
    resource = setup()
    try:
        yield resource
    finally:
        teardown(resource)
