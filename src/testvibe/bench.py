"""S5 bench helpers — scale-fixture generation + regression comparator.

Task A6. These helpers build the perf fixtures the S5 surface benchmarks against:

* ``scale_tree`` — many small files (RC1 scale axis).
* ``sparse_file`` — a few large files summing toward the size-guard threshold
  (RC2 total-bytes axis), created SPARSE so the fixture exercises the guard
  without actually allocating GiB of disk.
* ``compare_to_baseline`` — the regression gate: fail a perf run when it
  exceeds a committed baseline by more than an allowed percentage.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["compare_to_baseline", "scale_tree", "sparse_file"]


def scale_tree(target, count, kb_each: int = 1) -> Path:
    """Create ``count`` files under ``target`` (each ``kb_each`` KiB).

    Returns the target directory (as a ``Path``). The directory is created if
    needed. Each file holds exactly ``kb_each * 1024`` bytes so the tree's total
    size is deterministic — benchmarks must not depend on filesystem noise.
    """
    root = Path(target)
    root.mkdir(parents=True, exist_ok=True)
    chunk = b"\x00" * (int(kb_each) * 1024)
    for i in range(int(count)):
        (root / f"f{i:06d}.dat").write_bytes(chunk)
    return root


def sparse_file(path, mb: int) -> Path:
    """Create a sparse file whose LOGICAL size is ``mb`` MiB.

    Uses ``ftruncate`` (via ``truncate``/seek) so no real bytes are allocated —
    ``st_size`` reports ``mb`` MiB while ``st_blocks`` stays near zero. This is
    what makes the RC2 total-bytes fixture cheap: it proves a size guard refuses
    before GiB-scale indexing without burning GiB of disk.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    size = int(mb) * 1024 * 1024
    # Open for write (creates + truncates to empty), then grow the logical size
    # via ftruncate. On POSIX this leaves the file sparse (no data blocks).
    with p.open("wb") as fh:
        fh.truncate(size)
    return p


def compare_to_baseline(
    current_ms: float, baseline_ms: float, regress_pct: float
) -> bool:
    """Return True when ``current_ms`` is within tolerance (NOT a regression).

    A regression is strictly EXCEEDING the baseline by more than the allowed
    percentage: ``current_ms > baseline_ms * (1 + regress_pct/100)``. Exactly at
    the threshold counts as within tolerance (not a regression). The threshold
    is computed as ``baseline_ms * (100 + regress_pct) / 100`` to keep the
    integer-ish math grouped — this avoids a float-representation pitfall where
    ``baseline*(1+pct/100)`` lands just below the exact threshold (e.g.
    ``100*(1+0.15) == 114.99999999999999``) and flips the boundary case.
    """
    threshold = baseline_ms * (100.0 + regress_pct) / 100.0
    return not (current_ms > threshold)
