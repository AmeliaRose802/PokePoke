"""Tests for run-log retention helpers."""

from pokepoke.utils.log_retention import RUN_ID_PATTERN, prune_old_run_dirs


def _make_run_dir(base, name):
    d = base / name
    d.mkdir()
    return d


def test_run_id_pattern_matches_valid_and_rejects_others():
    assert RUN_ID_PATTERN.match("20260619_144219_110f2255")
    assert not RUN_ID_PATTERN.match("not-a-run-dir")
    assert not RUN_ID_PATTERN.match("20260619_144219_ZZZZ")


def test_prune_keeps_most_recent(tmp_path):
    for i in range(6):
        _make_run_dir(tmp_path, f"2026010{i}_120000_abcdef0{i}")

    prune_old_run_dirs(tmp_path, max_runs=2, keep_name="20260105_120000_abcdef05")

    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["20260104_120000_abcdef04", "20260105_120000_abcdef05"]


def test_prune_always_keeps_named_run(tmp_path):
    # The named (current) run is the oldest; it must survive pruning.
    keep = "20260101_120000_abcdef01"
    _make_run_dir(tmp_path, keep)
    for i in range(2, 6):
        _make_run_dir(tmp_path, f"2026010{i}_120000_abcdef0{i}")

    prune_old_run_dirs(tmp_path, max_runs=1, keep_name=keep)

    names = {p.name for p in tmp_path.iterdir()}
    assert keep in names


def test_prune_disabled_with_non_positive_max_runs(tmp_path):
    for i in range(3):
        _make_run_dir(tmp_path, f"2026010{i}_120000_abcdef0{i}")

    prune_old_run_dirs(tmp_path, max_runs=0, keep_name="x")
    prune_old_run_dirs(tmp_path, max_runs=-5, keep_name="x")

    assert len([p for p in tmp_path.iterdir()]) == 3


def test_prune_ignores_non_run_dirs(tmp_path):
    (tmp_path / "important_data").mkdir()
    (tmp_path / "not-a-run").mkdir()
    for i in range(3):
        _make_run_dir(tmp_path, f"2026010{i}_120000_abcdef0{i}")

    prune_old_run_dirs(tmp_path, max_runs=1, keep_name="20260102_120000_abcdef02")

    names = {p.name for p in tmp_path.iterdir()}
    assert "important_data" in names
    assert "not-a-run" in names


def test_prune_noop_when_under_limit(tmp_path):
    for i in range(2):
        _make_run_dir(tmp_path, f"2026010{i}_120000_abcdef0{i}")

    prune_old_run_dirs(tmp_path, max_runs=10, keep_name="x")

    assert len([p for p in tmp_path.iterdir()]) == 2


def test_prune_handles_missing_base_dir(tmp_path):
    missing = tmp_path / "does-not-exist"
    # Should not raise even though the directory cannot be listed.
    prune_old_run_dirs(missing, max_runs=1, keep_name="x")
