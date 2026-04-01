"""Tests for gate rejection stats persistence and summarization."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pokepoke.stats.gate_rejection_tracker import (
    _rebuild_gate_summary,
    _update_gate_summary_incremental,
    get_gate_rejection_stats,
    load_gate_stats,
    print_gate_rejection_leaderboard,
    record_gate_check,
)


@pytest.fixture()
def _chdir_tmp(tmp_path: Path):
    """Run test with CWD set to tmp_path so .pokepoke/locks stays isolated."""
    original = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield
    finally:
        os.chdir(original)


def test_missing_file_loads_empty_store(tmp_path: Path, _chdir_tmp) -> None:
    stats_path = tmp_path / "gate_stats.json"
    data = load_gate_stats(stats_path)
    assert data == {"log": [], "summary": {}}


def test_record_gate_check_persists_and_updates_summary(tmp_path: Path, _chdir_tmp) -> None:
    stats_path = tmp_path / "gate_stats.json"

    record_gate_check("gate-model-A", "PP-1", passed=True, path=stats_path)
    record_gate_check("gate-model-A", "PP-2", passed=False, path=stats_path)

    assert stats_path.exists()

    stats = get_gate_rejection_stats(stats_path)
    assert "gate-model-A" in stats

    s = stats["gate-model-A"]
    assert s["total_checks"] == 2
    assert s["total_passed"] == 1
    assert s["total_rejected"] == 1
    assert s["rejection_rate"] == 0.5
    assert s["last_used"]
    assert len(s["trend"]) == 2


def test_rebuild_summary_matches_incremental_fold() -> None:
    log = [
        {"gate_model": "m1", "passed": True, "timestamp": "2026-01-01T00:00:00"},
        {"gate_model": "m1", "passed": False, "timestamp": "2026-01-01T00:01:00"},
        {"gate_model": "m2", "passed": False, "timestamp": "2026-01-01T00:02:00"},
    ]

    rebuilt = _rebuild_gate_summary(log)

    incremental: dict[str, dict] = {}
    for entry in log:
        _update_gate_summary_incremental(incremental, entry)

    assert set(rebuilt.keys()) == set(incremental.keys())
    for model in rebuilt:
        assert rebuilt[model]["total_checks"] == incremental[model]["total_checks"]
        assert rebuilt[model]["total_passed"] == incremental[model]["total_passed"]
        assert rebuilt[model]["total_rejected"] == incremental[model]["total_rejected"]
        assert rebuilt[model]["rejection_rate"] == incremental[model]["rejection_rate"]
        assert rebuilt[model]["last_used"] == incremental[model]["last_used"]
        assert rebuilt[model]["trend"] == incremental[model]["trend"]


def test_trend_capped_to_50() -> None:
    summary: dict[str, dict] = {}
    for i in range(60):
        entry = {
            "gate_model": "m1",
            "passed": (i % 2 == 0),
            "timestamp": f"2026-01-01T00:{i:02d}:00",
        }
        _update_gate_summary_incremental(summary, entry)

    assert len(summary["m1"]["trend"]) == 50


def test_log_capped_at_max_entries(tmp_path: Path, _chdir_tmp, monkeypatch) -> None:
    """Test that the raw log evicts oldest half when reaching _MAX_LOG_ENTRIES."""
    import pokepoke.stats.gate_rejection_tracker as grt

    monkeypatch.setattr(grt, "_MAX_LOG_ENTRIES", 20)
    stats_path = tmp_path / "gate_stats.json"

    for i in range(25):
        record_gate_check(f"model-{i % 3}", f"PP-{i}", passed=(i % 2 == 0), path=stats_path)

    data = load_gate_stats(stats_path)
    assert len(data["log"]) <= 20


def test_log_eviction_preserves_summary_accuracy(tmp_path: Path, _chdir_tmp, monkeypatch) -> None:
    """Test that summary counters remain correct after log eviction."""
    import pokepoke.stats.gate_rejection_tracker as grt

    monkeypatch.setattr(grt, "_MAX_LOG_ENTRIES", 10)
    stats_path = tmp_path / "gate_stats.json"

    for i in range(15):
        record_gate_check("model-A", f"PP-{i}", passed=(i % 2 == 0), path=stats_path)

    stats = get_gate_rejection_stats(stats_path)
    assert stats["model-A"]["total_checks"] == 15


def test_print_leaderboard_logs_output(tmp_path: Path, _chdir_tmp, caplog) -> None:
    stats_path = tmp_path / "gate_stats.json"
    record_gate_check("m1", "PP-1", passed=False, path=stats_path)

    caplog.set_level("INFO")
    print_gate_rejection_leaderboard(stats_path)

    text = "\n".join(r.message for r in caplog.records)
    assert "Gate Agent Rejection Rates" in text
    assert "m1" in text
