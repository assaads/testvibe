"""testvibe.dogfood — S4 telemetry helpers: CPU/RSS sampling, diff assertion,
and the RC5-spin regression detector.

Dogfood scenarios (``@scenario(kind="dogfood")``) drive a tool end-to-end on
the real host and assert it behaves sanely. The helpers here measure resource
telemetry without a ``psutil`` dependency:

* :func:`sample_cpu_rss` — ``(cpu_pct, rss_mb)`` via ``os.times()`` CPU deltas
  and the ``VmRSS:`` line of ``/proc/self/status`` (with a portable fallback).
* :func:`assert_empty_diff` — compare two directory trees byte-for-byte; assert
  on any difference (used to verify a full-cycle dogfood restores faithfully).
* :func:`assert_no_regression` — flag the **RC5 spin signature**: sustained
  high CPU while RSS stays flat (a busy-loop that is not making progress).

No ``psutil``: CPU comes from ``os.times()`` deltas and RSS from ``/proc`` so
the helpers work with the standard library only. The ``/proc`` read is guarded
so tests pass on any host (non-Linux → RSS falls back to ``0.0``).
"""

from __future__ import annotations

import os
import time

__all__ = ["assert_empty_diff", "assert_no_regression", "sample_cpu_rss"]

# Interval between the two os.times() samples used to derive a CPU percentage.
# Small enough to be cheap, large enough that the delta is meaningful.
_SAMPLE_INTERVAL_S = 0.01


def _read_vmrss_mb() -> float:
    """Read current RSS in MB from ``/proc/self/status``.

    Returns ``0.0`` when ``/proc`` is unavailable or the line cannot be parsed
    (non-Linux hosts, restricted sandboxes), so callers never crash on a
    missing procfs.
    """
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    # "VmRSS:\t   12345 kB"
                    parts = line.split()
                    # parts == ["VmRSS:", "<kB>", "kB"]
                    return int(parts[1]) / 1024.0
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def sample_cpu_rss() -> tuple[float, float]:
    """Sample current CPU% and RSS in MB.

    CPU% is derived from two ``os.times()`` samples taken ``_SAMPLE_INTERVAL_S``
    apart: ``(user+system delta) / elapsed delta * 100``. RSS is read from
    ``/proc/self/status`` (``VmRSS:``), falling back to ``0.0`` off-Linux.

    Returns a ``(cpu_pct, rss_mb)`` pair of non-negative floats.
    """
    t1 = os.times()
    time.sleep(_SAMPLE_INTERVAL_S)
    t2 = os.times()
    cpu_delta = (t2.user - t1.user) + (t2.system - t1.system)
    wall_delta = t2.elapsed - t1.elapsed
    cpu_pct = (cpu_delta / wall_delta * 100.0) if wall_delta > 0 else 0.0
    cpu_pct = max(cpu_pct, 0.0)
    rss_mb = _read_vmrss_mb()
    return (cpu_pct, rss_mb)


def _collect_tree(root: str) -> dict[str, bytes]:
    """Walk ``root`` and return ``{relative_path: file_bytes}``."""
    result: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root)
            with open(full, "rb") as fh:
                result[rel] = fh.read()
    return result


def assert_empty_diff(src: str, restored: str) -> None:
    """Assert that two directory trees ``src`` and ``restored`` are identical.

    Compares the set of relative file paths and the byte content of each.
    Raises :class:`AssertionError` on any difference (missing/extra file or
    differing content). Used by full-cycle dogfoods to confirm a backup/restore
    round-trip reproduces the source tree exactly.
    """
    src_files = _collect_tree(src)
    rest_files = _collect_tree(restored)
    if set(src_files) != set(rest_files):
        missing = sorted(set(src_files) - set(rest_files))
        extra = sorted(set(rest_files) - set(src_files))
        raise AssertionError(f"tree file sets differ: missing={missing}, extra={extra}")
    for rel, content in src_files.items():
        if content != rest_files[rel]:
            raise AssertionError(f"file content differs: {rel}")


def assert_no_regression(
    samples: list[tuple[float, float]], *, cpu_pct: float, flat_rss_eps_mb: float
) -> None:
    """Flag the RC5 spin signature in a telemetry ``samples`` sequence.

    Each sample is a ``(cpu_pct, rss_mb)`` pair. The RC5 signature is
    **sustained high CPU across all samples while RSS stays flat** — a busy
    loop that burns CPU without allocating memory (no forward progress). When
    detected this raises :class:`AssertionError`.

    The check **clears** (does not raise) when RSS is rising across samples
    (work is progressing, memory growing) or when CPU is not sustained high.
    Fewer than two samples cannot demonstrate a *sustained* spin, so the check
    also clears for empty / single-sample input.

    Parameters:

    * ``cpu_pct``          — threshold above which CPU counts as "high".
    * ``flat_rss_eps_mb``  — RSS range (max - min) at or below which RSS counts
      as "flat".
    """
    if len(samples) < 2:
        return
    cpu_values = [s[0] for s in samples]
    rss_values = [s[1] for s in samples]
    rss_floor = min(rss_values)
    rss_range = max(rss_values) - rss_floor
    sustained_high_cpu = all(c >= cpu_pct for c in cpu_values)
    flat_rss = rss_range <= flat_rss_eps_mb
    if sustained_high_cpu and flat_rss:
        raise AssertionError(
            f"RC5 spin signature: CPU sustained >= {cpu_pct}% across "
            f"{len(samples)} samples while RSS flat within {flat_rss_eps_mb}MB "
            f"(floor={rss_floor}MB, range={rss_range}MB)"
        )
