"""S5 bench helpers — ``scale_tree``, ``sparse_file``, ``compare_to_baseline``.

Task A6. These tests pin the bench-fixture helpers used to generate scale trees
(many small files, RC1 scale axis) and sparse files (RC2 total-bytes axis), plus
the regression comparator that gates perf on a committed baseline.
"""

import os
import pathlib
import stat

import pytest


# --------------------------------------------------------------------------- #
# scale_tree
# --------------------------------------------------------------------------- #
def test_scale_tree_creates_requested_count(tmp_path: pathlib.Path):
    from testvibe.bench import scale_tree

    target = tmp_path / "tree"
    returned = scale_tree(target, 50)

    assert returned == target                      # returns the target dir
    assert target.is_dir()
    files = [p for p in target.iterdir() if p.is_file()]
    assert len(files) == 50


def test_scale_tree_file_sizes_match_kb_each(tmp_path: pathlib.Path):
    from testvibe.bench import scale_tree

    target = tmp_path / "tree4k"
    scale_tree(target, 5, kb_each=4)

    files = list(target.iterdir())
    assert len(files) == 5
    for f in files:
        # each file is ~4 KiB -> exactly 4 * 1024 bytes of real data
        assert f.stat().st_size == 4 * 1024


def test_scale_tree_default_kb_each_is_one_kib(tmp_path: pathlib.Path):
    from testvibe.bench import scale_tree

    target = tmp_path / "default"
    scale_tree(target, 3)

    for f in target.iterdir():
        assert f.stat().st_size == 1024


# --------------------------------------------------------------------------- #
# sparse_file
# --------------------------------------------------------------------------- #
def test_sparse_file_logical_size_is_one_mib(tmp_path: pathlib.Path):
    from testvibe.bench import sparse_file

    p = tmp_path / "sparse.bin"
    returned = sparse_file(p, 1)

    assert returned == p
    logical = os.path.getsize(p)
    assert logical == 1 * 1024 * 1024             # exactly 1 MiB logical


def test_sparse_file_is_actually_sparse(tmp_path: pathlib.Path):
    """A sparse file must NOT allocate its full logical size on disk.

    Guards against an implementation that writes ``mb`` MiB of zeros (which
    would defeat the RC2 total-bytes purpose: exercising the size guard without
    burning disk). We assert the allocated blocks are far smaller than the
    logical size.
    """
    from testvibe.bench import sparse_file

    p = tmp_path / "big.bin"
    mb = 4
    sparse_file(p, mb)

    st = os.stat(p)
    logical = mb * 1024 * 1024
    assert stat.S_ISREG(st.st_mode)
    allocated = st.st_blocks * 512                # st_blocks is in 512-byte units
    assert allocated < logical // 2, (
        f"sparse file allocated {allocated} bytes for a {logical}-byte logical "
        f"size — it is NOT sparse"
    )


# --------------------------------------------------------------------------- #
# compare_to_baseline
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "current, baseline, regress_pct, expected",
    [
        (120, 100, 15, False),   # 120 > 115 -> regression -> within tolerance? False
        (100, 100, 15, True),    # 100 <= 115 -> within tolerance -> True
        (115, 100, 15, True),    # exactly at threshold -> NOT exceeding -> True
        (116, 100, 15, False),   # 116 > 115 -> regression -> False
        (0, 100, 15, True),      # zero-time is never a regression
    ],
)
def test_compare_to_baseline(current, baseline, regress_pct, expected):
    from testvibe.bench import compare_to_baseline

    assert compare_to_baseline(current, baseline, regress_pct) is expected


def test_compare_to_baseline_acceptance_case():
    """Plan acceptance: compare_to_baseline(120, 100, 15) -> False."""
    from testvibe.bench import compare_to_baseline

    assert compare_to_baseline(120, 100, 15) is False
