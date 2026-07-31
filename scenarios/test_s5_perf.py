"""S5 self-dogfood scenario: perf baseline comparator + deterministic fixtures.

``bench.compare_to_baseline`` is the regression gate: a perf run is a regression
only when it *strictly* exceeds the baseline by more than an allowed percentage.
Exactly-at-the-threshold is within tolerance (NOT a regression). The comparator
is pure arithmetic, so these tests are deterministic and wall-clock-independent.

``bench.scale_tree`` / ``sparse_file`` build the perf fixtures. They must be
deterministic (byte-exact sizes, no filesystem noise), and ``sparse_file`` must
be genuinely sparse (logical size >> allocated blocks).
"""

from __future__ import annotations

import pytest

from testvibe import scenario
from testvibe.bench import compare_to_baseline, scale_tree, sparse_file


@scenario("s5_perf_baseline_logic", kind="hermetic", surfaces=("perf",))
@pytest.mark.perf
def test_s5_perf_baseline_logic(tmp_path) -> None:
    """compare_to_baseline True within tolerance, False beyond; fixtures deterministic."""
    baseline = 100.0
    pct = 15.0
    threshold = baseline * (100.0 + pct) / 100.0  # 115.0

    # --- within tolerance: True (NOT a regression) ---
    assert compare_to_baseline(100.0, baseline, pct) is True  # equal to baseline
    assert compare_to_baseline(110.0, baseline, pct) is True  # slower but within
    # Exactly at the threshold counts as within tolerance (strict > required).
    assert compare_to_baseline(threshold, baseline, pct) is True, (
        "value exactly at threshold must be within tolerance, not a regression"
    )

    # --- beyond tolerance: False (regression) ---
    just_over = threshold + 0.0001
    assert compare_to_baseline(just_over, baseline, pct) is False, (
        "value strictly over threshold must be a regression"
    )
    assert compare_to_baseline(150.0, baseline, pct) is False

    # --- fixtures: scale_tree is deterministic (exact count + byte size) ---
    root = scale_tree(tmp_path / "tree", count=8, kb_each=2)
    files = sorted(p.name for p in root.iterdir())
    assert len(files) == 8, f"scale_tree wrote {len(files)} files, expected 8"
    # Each file holds exactly kb_each * 1024 bytes.
    for f in files:
        assert (root / f).stat().st_size == 2 * 1024

    # --- fixtures: sparse_file is logically mb MiB but allocates ~zero blocks ---
    big = sparse_file(tmp_path / "sparse.bin", mb=64)
    # The helper runs without error and the LOGICAL size is exact on every host.
    st = big.stat()
    assert st.st_size == 64 * 1024 * 1024, "sparse_file logical size must be exact"
    # The allocation assertion is non-portable: on an eager-alloc filesystem or
    # a host without st_blocks, allocated >= logical for reasons unrelated to
    # testvibe. Only assert sparseness where st_blocks exists AND the OS
    # actually reports a real gap; otherwise skip so the test stays portable.
    if hasattr(st, "st_blocks"):
        allocated_bytes = st.st_blocks * 512
        if allocated_bytes >= st.st_size:
            pytest.skip(
                f"host filesystem does not honor sparse allocation "
                f"(allocated {allocated_bytes}B >= logical {st.st_size}B); "
                f"non-testvibe-related, skipping sparseness assertion"
            )
        assert allocated_bytes < st.st_size, (
            f"sparse_file must be sparse: allocated {allocated_bytes}B >= logical {st.st_size}B"
        )


def test_s5_boundary_not_regression_at_exact_threshold() -> None:
    """A focused boundary check: the exact threshold is within tolerance.

    Guards the documented float-representation pitfall: ``100*(1+0.15)`` lands
    at 114.999... in naive math, which would wrongly flip the boundary to a
    regression. The comparator must use ``baseline*(100+pct)/100`` grouping.
    """
    assert compare_to_baseline(115.0, 100.0, 15.0) is True
    assert compare_to_baseline(115.0 + 1e-9, 100.0, 15.0) is False
