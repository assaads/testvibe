"""S0 gate helpers — env scrubbing for the pre-merge CI gate.

Task A6. The S0 gate runs the hermetic subset of the suite with tool-specific
env vars scrubbed, so the gate matches CI reality rather than the dev shell.
This closes the integration-seam class where a leaked tool-specific env var
(e.g. ``SYNCESTRA_*``) causes a false failure that exists on the laptop but not
in CI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

__all__ = ["scrub_env"]


def scrub_env(prefix: str, env: Mapping[str, str] | None = None) -> dict:
    """Return a NEW dict holding only keys NOT starting with ``prefix``.

    With ``env=None`` (default), scrub against a fresh copy of ``os.environ``.
    The input mapping is never mutated, and the returned dict is never the live
    ``os.environ`` object — the gate must operate on a detached snapshot so the
    running process is unaffected.
    """
    if env is None:
        env = dict(os.environ)
    return {k: v for k, v in env.items() if not k.startswith(prefix)}
