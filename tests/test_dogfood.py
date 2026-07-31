"""Tests for testvibe.dogfood — CPU/RSS telemetry + diff + RC5-spin signature (S4)."""

import pytest

from testvibe.dogfood import (
    assert_empty_diff,
    assert_no_regression,
    sample_cpu_rss,
)

# --- sample_cpu_rss ---


def test_sample_cpu_rss_returns_sane_pair():
    cpu, rss = sample_cpu_rss()
    # CPU% is a real number in [0, ~Ncores*100]; RSS is non-negative MB.
    assert isinstance(cpu, (int, float))
    assert isinstance(rss, (int, float))
    assert cpu >= 0.0
    assert rss >= 0.0


def test_sample_cpu_rss_portable_no_crash(monkeypatch):
    """sample_cpu_rss must not crash even when /proc is unavailable."""
    # Force the /proc reader to fail (simulates non-Linux host).
    real_open = open

    def blocked(path, *a, **k):
        if isinstance(path, str) and path.startswith("/proc/"):
            raise OSError("no /proc in test")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", blocked)
    cpu, rss = sample_cpu_rss()
    # RSS falls back to 0.0 gracefully; CPU still sampled via os.times().
    assert cpu >= 0.0
    assert rss == 0.0


# --- assert_no_regression: RC5 spin signature ---


def test_no_regression_flags_rc5_spin_signature():
    """Sustained-high-CPU + flat-RSS = the RC5 spin signature -> regression."""
    samples = [(90.0, 100.0), (91.0, 101.0), (92.0, 100.5)]
    with pytest.raises(AssertionError):
        assert_no_regression(samples, cpu_pct=50, flat_rss_eps_mb=8)


def test_no_regression_clears_when_rss_rising():
    """RSS rising across samples = work is progressing -> no regression."""
    samples = [(90.0, 100.0), (91.0, 120.0), (92.0, 150.0)]
    # flat_rss_eps_mb=8 but RSS range is 50 -> rising -> clears.
    assert_no_regression(samples, cpu_pct=50, flat_rss_eps_mb=8)  # must not raise


def test_no_regression_clears_when_cpu_not_sustained_high():
    """Low/intermittent CPU is not the spin signature -> no regression."""
    samples = [(10.0, 100.0), (11.0, 100.5), (12.0, 100.0)]
    assert_no_regression(samples, cpu_pct=50, flat_rss_eps_mb=8)  # must not raise


def test_no_regression_boundary_flat_within_eps():
    """RSS within eps of floor + sustained high CPU = still a regression."""
    samples = [(80.0, 100.0), (80.0, 108.0)]  # range exactly 8 == eps
    with pytest.raises(AssertionError):
        assert_no_regression(samples, cpu_pct=50, flat_rss_eps_mb=8)


def test_no_regression_empty_samples_clears():
    assert_no_regression([], cpu_pct=50, flat_rss_eps_mb=8)  # must not raise


def test_no_regression_single_sample_clears():
    """A single high-CPU sample cannot demonstrate a *sustained* spin, so it
    must not raise (false-positive guard on the RC5 spin signature).
    """
    assert_no_regression([(90.0, 100.0)], cpu_pct=50, flat_rss_eps_mb=8)  # must not raise


# --- assert_empty_diff ---


def test_assert_empty_diff_identical_trees(tmp_path):
    src = tmp_path / "src"
    rest = tmp_path / "rest"
    src.mkdir()
    rest.mkdir()
    (src / "a.txt").write_bytes(b"hello")
    (src / "sub").mkdir()
    (src / "sub" / "b.txt").write_bytes(b"world")
    (rest / "a.txt").write_bytes(b"hello")
    (rest / "sub").mkdir()
    (rest / "sub" / "b.txt").write_bytes(b"world")
    # must not raise
    assert_empty_diff(str(src), str(rest))


def test_assert_empty_diff_detects_content_change(tmp_path):
    src = tmp_path / "src"
    rest = tmp_path / "rest"
    src.mkdir()
    rest.mkdir()
    (src / "a.txt").write_bytes(b"hello")
    (rest / "a.txt").write_bytes(b"HELLO")  # different content
    with pytest.raises(AssertionError):
        assert_empty_diff(str(src), str(rest))


def test_assert_empty_diff_detects_missing_file(tmp_path):
    src = tmp_path / "src"
    rest = tmp_path / "rest"
    src.mkdir()
    rest.mkdir()
    (src / "a.txt").write_bytes(b"hello")
    (src / "b.txt").write_bytes(b"world")
    (rest / "a.txt").write_bytes(b"hello")  # b.txt missing on restored side
    with pytest.raises(AssertionError):
        assert_empty_diff(str(src), str(rest))
