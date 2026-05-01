"""Tests for gate rejection stats persistence and summarization."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pokepoke.stats.gate_rejection_tracker import (
    _update_gate_summary_incremental,
    get_gate_rejection_stats,
    get_per_item_rejection_stats,
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

def test_record_gate_check_with_reason(tmp_path: Path, _chdir_tmp) -> None:
    """Test that reason is stored in the log entry when provided."""
    stats_path = tmp_path / "gate_stats.json"

    record_gate_check("m1", "PP-1", passed=False, path=stats_path, reason="Tests failed: 3 errors")
    record_gate_check("m1", "PP-2", passed=True, path=stats_path)

    data = load_gate_stats(stats_path)
    assert len(data["log"]) == 2
    assert data["log"][0]["reason"] == "Tests failed: 3 errors"
    assert "reason" not in data["log"][1]  # No reason for passing checks

def test_get_per_item_rejection_stats_empty(tmp_path: Path, _chdir_tmp) -> None:
    """Test that per-item stats returns empty dict for missing file."""
    stats_path = tmp_path / "gate_stats.json"
    result = get_per_item_rejection_stats(stats_path)
    assert result == {}

def test_get_per_item_rejection_stats_aggregates(tmp_path: Path, _chdir_tmp) -> None:
    """Test that per-item stats aggregates checks per item correctly."""
    stats_path = tmp_path / "gate_stats.json"

    record_gate_check("m1", "PP-1", passed=False, path=stats_path, reason="lint failed")
    record_gate_check("m1", "PP-1", passed=False, path=stats_path, reason="coverage low")
    record_gate_check("m2", "PP-1", passed=True, path=stats_path)
    record_gate_check("m1", "PP-2", passed=True, path=stats_path)

    result = get_per_item_rejection_stats(stats_path)
    assert "PP-1" in result
    assert "PP-2" in result

    pp1 = result["PP-1"]
    assert pp1["total_checks"] == 3
    assert pp1["rejections"] == 2
    assert sorted(pp1["gate_models_used"]) == ["m1", "m2"]
    assert pp1["reasons"] == ["lint failed", "coverage low"]
    assert pp1["last_check"]  # Has a timestamp

    pp2 = result["PP-2"]
    assert pp2["total_checks"] == 1
    assert pp2["rejections"] == 0
    assert pp2["gate_models_used"] == ["m1"]
    assert pp2["reasons"] == []

def test_per_item_reasons_capped_at_five(tmp_path: Path, _chdir_tmp) -> None:
    """Test that per-item reasons are capped at 5 most recent."""
    stats_path = tmp_path / "gate_stats.json"

    for i in range(8):
        record_gate_check("m1", "PP-1", passed=False, path=stats_path, reason=f"reason-{i}")

    result = get_per_item_rejection_stats(stats_path)
    reasons = result["PP-1"]["reasons"]
    assert len(reasons) == 5
    assert reasons[0] == "reason-3"
    assert reasons[-1] == "reason-7"
