"""Tests for persistent model performance stats store.

Covers:
- load_model_stats: reading from disk, handling missing/corrupt files
- save_model_stats: atomic write
- record_completion: single-record append + summary update
- get_model_summary: read-only summary access
- get_model_weights: performance-weighted selection weights
- print_model_leaderboard: human-readable output
- _rebuild_summary: summary recomputation from log
- cross-process locking: multi-agent safety
"""

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from pokepoke.types import ModelCompletionRecord
from pokepoke.model_stats_store import (
    load_model_stats,
    save_model_stats,
    record_completion,
    get_model_summary,
    get_model_weights,
    get_model_history,
    print_model_leaderboard,
    _rebuild_summary,
    _update_summary_incremental,
    _empty_store,
    _record_to_dict,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _tmp_stats_path(tmp_path: Path) -> Path:
    """Return a temporary model_stats.json path inside tmp_path."""
    return tmp_path / "model_stats.json"


def _make_record(
    item_id: str = "PP-1",
    model: str = "gpt-4o",
    duration: float = 60.0,
    gate_passed: bool = True,
) -> ModelCompletionRecord:
    return ModelCompletionRecord(
        item_id=item_id,
        model=model,
        duration_seconds=duration,
        gate_passed=gate_passed,
    )


# ── _empty_store ─────────────────────────────────────────────────────

class TestEmptyStore:
    def test_returns_log_and_summary(self):
        store = _empty_store()
        assert store == {"log": [], "summary": {}}

    def test_returns_fresh_instance(self):
        a = _empty_store()
        b = _empty_store()
        assert a is not b


# ── load_model_stats ─────────────────────────────────────────────────

class TestLoadModelStats:
    def test_returns_empty_when_file_missing(self, tmp_path: Path):
        result = load_model_stats(tmp_path / "nonexistent.json")
        assert result == {"log": [], "summary": {}}

    def test_loads_valid_file(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        data = {"log": [{"model": "gpt-4o", "item_id": "X"}], "summary": {}}
        path.write_text(json.dumps(data))
        result = load_model_stats(path)
        assert result["log"] == [{"model": "gpt-4o", "item_id": "X"}]

    def test_returns_empty_on_corrupt_json(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        path.write_text("not json at all {{{")
        result = load_model_stats(path)
        assert result == {"log": [], "summary": {}}

    def test_returns_empty_on_missing_log_key(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        path.write_text(json.dumps({"summary": {}}))
        result = load_model_stats(path)
        assert result == {"log": [], "summary": {}}

    def test_returns_empty_on_non_dict(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        path.write_text(json.dumps([1, 2, 3]))
        result = load_model_stats(path)
        assert result == {"log": [], "summary": {}}


# ── save_model_stats ─────────────────────────────────────────────────

class TestSaveModelStats:
    def test_creates_file(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        data = {"log": [], "summary": {}}
        save_model_stats(data, path)
        assert path.exists()
        assert json.loads(path.read_text()) == data

    def test_overwrites_existing(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        save_model_stats({"log": [{"a": 1}], "summary": {}}, path)
        save_model_stats({"log": [{"b": 2}], "summary": {}}, path)
        result = json.loads(path.read_text())
        assert len(result["log"]) == 1
        assert result["log"][0] == {"b": 2}

    def test_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "stats.json"
        save_model_stats({"log": [], "summary": {}}, path)
        assert path.exists()


# ── _record_to_dict ──────────────────────────────────────────────────

class TestRecordToDict:
    def test_includes_all_fields(self):
        rec = _make_record(item_id="PP-5", model="claude-opus-4.6", duration=120.5, gate_passed=False)
        d = _record_to_dict(rec)
        assert d["item_id"] == "PP-5"
        assert d["model"] == "claude-opus-4.6"
        assert d["duration_seconds"] == 120.5
        assert d["gate_passed"] is False
        assert "timestamp" in d

    def test_none_gate_passed(self):
        rec = ModelCompletionRecord(item_id="X", model="m", duration_seconds=1.0, gate_passed=None)
        d = _record_to_dict(rec)
        assert d["gate_passed"] is None


# ── _rebuild_summary ─────────────────────────────────────────────────

class TestRebuildSummary:
    def test_empty_log(self):
        assert _rebuild_summary([]) == {}

    def test_single_success(self):
        log = [{"model": "gpt-4o", "duration_seconds": 60.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"}]
        summary = _rebuild_summary(log)
        assert "gpt-4o" in summary
        s = summary["gpt-4o"]
        assert s["total_items_attempted"] == 1
        assert s["total_items_succeeded"] == 1
        assert s["total_items_failed"] == 0
        assert s["success_rate"] == 1.0
        assert s["average_duration"] == 60.0
        assert s["median_duration"] == 60.0
        assert s["stddev_duration"] == 0.0  # single entry → 0

    def test_mixed_results(self):
        log = [
            {"model": "m1", "duration_seconds": 50.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            {"model": "m1", "duration_seconds": 70.0, "gate_passed": False, "timestamp": "2026-01-01T00:01:00"},
            {"model": "m1", "duration_seconds": 80.0, "gate_passed": True, "timestamp": "2026-01-01T00:02:00"},
        ]
        summary = _rebuild_summary(log)
        s = summary["m1"]
        assert s["total_items_attempted"] == 3
        assert s["total_items_succeeded"] == 2
        assert s["total_items_failed"] == 1
        assert s["success_rate"] == pytest.approx(0.6667, abs=0.01)
        assert s["average_duration"] == pytest.approx(66.67, abs=0.01)
        assert s["median_duration"] == 70.0
        assert s["stddev_duration"] == pytest.approx(12.47, abs=0.1)

    def test_none_gate_not_counted(self):
        log = [
            {"model": "m1", "duration_seconds": 30.0, "gate_passed": None, "timestamp": "2026-01-01T00:00:00"},
        ]
        summary = _rebuild_summary(log)
        s = summary["m1"]
        assert s["total_items_attempted"] == 1
        assert s["total_items_succeeded"] == 0
        assert s["total_items_failed"] == 0
        assert s["success_rate"] == 0.0  # 0/0 → 0.0

    def test_multiple_models(self):
        log = [
            {"model": "m1", "duration_seconds": 40.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            {"model": "m2", "duration_seconds": 90.0, "gate_passed": False, "timestamp": "2026-01-01T00:01:00"},
        ]
        summary = _rebuild_summary(log)
        assert len(summary) == 2
        assert summary["m1"]["success_rate"] == 1.0
        assert summary["m2"]["success_rate"] == 0.0

    def test_last_used_is_latest(self):
        log = [
            {"model": "m1", "duration_seconds": 10.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            {"model": "m1", "duration_seconds": 10.0, "gate_passed": True, "timestamp": "2026-02-15T12:00:00"},
        ]
        summary = _rebuild_summary(log)
        assert summary["m1"]["last_used"] == "2026-02-15T12:00:00"

    def test_median_robust_to_outlier(self):
        """Median should not be skewed by a single very long run."""
        log = [
            {"model": "m1", "duration_seconds": 40.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            {"model": "m1", "duration_seconds": 42.0, "gate_passed": True, "timestamp": "2026-01-01T00:01:00"},
            {"model": "m1", "duration_seconds": 44.0, "gate_passed": True, "timestamp": "2026-01-01T00:02:00"},
            {"model": "m1", "duration_seconds": 46.0, "gate_passed": True, "timestamp": "2026-01-01T00:03:00"},
            {"model": "m1", "duration_seconds": 5000.0, "gate_passed": True, "timestamp": "2026-01-01T00:04:00"},
        ]
        summary = _rebuild_summary(log)
        s = summary["m1"]
        # Median should be 44, not the mean of ~1034.4
        assert s["median_duration"] == 44.0
        assert s["average_duration"] == pytest.approx(1034.4, abs=1.0)
        assert s["stddev_duration"] > 0


# ── record_completion ────────────────────────────────────────────────

class TestRecordCompletion:
    def test_appends_to_empty_store(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        rec = _make_record()
        record_completion(rec, path)

        data = load_model_stats(path)
        assert len(data["log"]) == 1
        assert data["log"][0]["model"] == "gpt-4o"
        assert "gpt-4o" in data["summary"]

    def test_appends_to_existing_store(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        record_completion(_make_record(item_id="A"), path)
        record_completion(_make_record(item_id="B"), path)

        data = load_model_stats(path)
        assert len(data["log"]) == 2
        assert data["summary"]["gpt-4o"]["total_items_attempted"] == 2

    def test_updates_summary_correctly(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        record_completion(_make_record(gate_passed=True), path)
        record_completion(_make_record(gate_passed=False), path)

        summary = get_model_summary(path)
        assert summary["gpt-4o"]["total_items_succeeded"] == 1
        assert summary["gpt-4o"]["total_items_failed"] == 1
        assert summary["gpt-4o"]["success_rate"] == 0.5


# ── get_model_summary ────────────────────────────────────────────────

class TestGetModelSummary:
    def test_empty_when_no_file(self, tmp_path: Path):
        assert get_model_summary(tmp_path / "nope.json") == {}

    def test_returns_summary_dict(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        record_completion(_make_record(), path)
        summary = get_model_summary(path)
        assert "gpt-4o" in summary
        assert summary["gpt-4o"]["total_items_attempted"] == 1


# ── get_model_history ──────────────────────────────────────────────────


class TestGetModelHistory:
    def test_empty_when_no_file(self, tmp_path: Path):
        assert get_model_history(tmp_path / "missing.json") == []

    def test_returns_last_n_entries(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        for rec in [
            _make_record(item_id="A", model="m1"),
            _make_record(item_id="B", model="m2"),
            _make_record(item_id="C", model="m3"),
        ]:
            record_completion(rec, path)

        history = get_model_history(path, limit=2)
        assert len(history) == 2
        assert history[0]["item_id"] == "B"
        assert history[1]["item_id"] == "C"

    def test_limit_zero_returns_empty(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        record_completion(_make_record(item_id="only"), path)
        assert get_model_history(path, limit=0) == []


# ── get_model_weights ────────────────────────────────────────────────

class TestGetModelWeights:
    def test_empty_when_no_data(self, tmp_path: Path):
        assert get_model_weights(tmp_path / "nope.json") == {}

    def test_neutral_weight_below_min_attempts(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        record_completion(_make_record(model="m1"), path)
        weights = get_model_weights(path, min_attempts=3)
        assert weights["m1"] == 1.0

    def test_weighted_above_min_attempts(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        # 3 successes, 1 failure = 75% success rate
        for i in range(3):
            record_completion(_make_record(item_id=f"S{i}", model="m1", gate_passed=True), path)
        record_completion(_make_record(item_id="F1", model="m1", gate_passed=False), path)

        weights = get_model_weights(path, min_attempts=3)
        assert weights["m1"] == pytest.approx(0.75, abs=0.01)

    def test_floor_weight_for_poor_model(self, tmp_path: Path):
        path = _tmp_stats_path(tmp_path)
        # 3 failures = 0% → floor of 0.1
        for i in range(3):
            record_completion(_make_record(item_id=f"F{i}", model="bad", gate_passed=False), path)

        weights = get_model_weights(path, min_attempts=3)
        assert weights["bad"] == 0.1


# ── print_model_leaderboard ──────────────────────────────────────────

class TestPrintModelLeaderboard:
    def test_no_data(self, tmp_path: Path, capsys):
        print_model_leaderboard(tmp_path / "nope.json")
        captured = capsys.readouterr()
        assert "No model performance data" in captured.out

    def test_with_data(self, tmp_path: Path, capsys):
        path = _tmp_stats_path(tmp_path)
        record_completion(_make_record(model="m1", gate_passed=True), path)
        record_completion(_make_record(model="m2", gate_passed=False), path)

        print_model_leaderboard(path)
        captured = capsys.readouterr()
        assert "Leaderboard" in captured.out
        assert "m1" in captured.out
        assert "m2" in captured.out
        assert "Median" in captured.out

    def test_sorted_by_success_rate(self, tmp_path: Path, capsys):
        path = _tmp_stats_path(tmp_path)
        # m1 = 100% success, m2 = 0%
        record_completion(_make_record(model="m1", gate_passed=True), path)
        record_completion(_make_record(model="m2", gate_passed=False), path)

        print_model_leaderboard(path)
        captured = capsys.readouterr()
        # m1 should appear before m2 in output
        assert captured.out.index("m1") < captured.out.index("m2")


# ── Cross-process locking ────────────────────────────────────────────

def _worker_record_completion(args):
    """Worker function for cross-process test. Must be module-level for pickling."""
    stats_path, item_id, model = args
    rec = ModelCompletionRecord(
        item_id=item_id,
        model=model,
        duration_seconds=1.0,
        gate_passed=True,
    )
    record_completion(rec, stats_path)


class TestCrossProcessLocking:
    """Test that concurrent writes from multiple processes don't lose records."""

    def test_concurrent_writes_preserve_all_records(self, tmp_path: Path):
        """Multiple processes writing concurrently should preserve all records.

        This test spawns multiple processes that each write a record. Without
        proper cross-process locking, some writes would be lost due to
        read-modify-write races. With filelock-based coordination, all records
        should be preserved.
        """
        # Use a shared path for the stats file
        stats_path = _tmp_stats_path(tmp_path)
        # Also need .pokepoke/locks directory for the file locks
        lock_dir = tmp_path / ".pokepoke" / "locks"
        lock_dir.mkdir(parents=True, exist_ok=True)

        # Change to tmp_path so that .pokepoke/locks is found
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)

            num_workers = 5
            records_per_worker = 4
            total_records = num_workers * records_per_worker

            # Prepare work items for each worker
            work_items = [
                (stats_path, f"item-{w}-{r}", f"model-{w}")
                for w in range(num_workers)
                for r in range(records_per_worker)
            ]

            # Use multiprocessing pool to simulate concurrent agents
            with multiprocessing.Pool(processes=num_workers) as pool:
                pool.map(_worker_record_completion, work_items)

            # Verify all records were preserved
            data = load_model_stats(stats_path)
            assert len(data["log"]) == total_records, (
                f"Expected {total_records} records, got {len(data['log'])}. "
                "Some records were lost due to race conditions."
            )

            # Verify each model has correct count
            for w in range(num_workers):
                model_name = f"model-{w}"
                model_records = [
                    e for e in data["log"] if e["model"] == model_name
                ]
                assert len(model_records) == records_per_worker, (
                    f"Model {model_name} should have {records_per_worker} "
                    f"records, got {len(model_records)}"
                )
        finally:
            os.chdir(original_cwd)


class TestGetModelHistoryEdgeCases:
    """Tests for get_model_history edge cases."""

    def test_returns_empty_for_non_list_log(self, tmp_path: Path) -> None:
        """Covers line 184: non-list log value."""
        stats_path = tmp_path / "model_stats.json"
        stats_path.write_text(json.dumps({"log": "not-a-list", "summary": {}}),
                              encoding="utf-8")
        result = get_model_history(limit=10, path=stats_path)
        assert result == []


# ── _update_summary_incremental ──────────────────────────────────────


class TestUpdateSummaryIncremental:
    def test_new_model(self):
        """Incremental update with a brand new model creates correct summary."""
        summary: dict = {}
        entry = {"model": "gpt-4o", "duration_seconds": 60.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"}
        _update_summary_incremental(summary, entry)
        assert "gpt-4o" in summary
        s = summary["gpt-4o"]
        assert s["total_items_attempted"] == 1
        assert s["total_items_succeeded"] == 1
        assert s["total_items_failed"] == 0
        assert s["success_rate"] == 1.0
        assert s["average_duration"] == 60.0
        assert s["median_duration"] == 60.0
        assert s["_durations"] == [60.0]

    def test_existing_model(self):
        """Incrementally adding to existing model updates correctly."""
        summary: dict = {}
        entries = [
            {"model": "m1", "duration_seconds": 50.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            {"model": "m1", "duration_seconds": 70.0, "gate_passed": False, "timestamp": "2026-01-01T00:01:00"},
            {"model": "m1", "duration_seconds": 80.0, "gate_passed": True, "timestamp": "2026-01-01T00:02:00"},
        ]
        for entry in entries:
            _update_summary_incremental(summary, entry)

        s = summary["m1"]
        assert s["total_items_attempted"] == 3
        assert s["total_items_succeeded"] == 2
        assert s["total_items_failed"] == 1
        assert s["success_rate"] == pytest.approx(0.6667, abs=0.01)
        assert s["average_duration"] == pytest.approx(66.67, abs=0.01)
        assert s["median_duration"] == 70.0

    def test_matches_full_rebuild(self):
        """Incremental updates produce the same result as a full rebuild."""
        log = [
            {"model": "m1", "duration_seconds": 50.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            {"model": "m1", "duration_seconds": 70.0, "gate_passed": False, "timestamp": "2026-01-01T00:01:00"},
            {"model": "m2", "duration_seconds": 90.0, "gate_passed": True, "timestamp": "2026-01-01T00:02:00"},
            {"model": "m1", "duration_seconds": 80.0, "gate_passed": True, "timestamp": "2026-01-01T00:03:00"},
        ]

        full_summary = _rebuild_summary(log)

        incr_summary: dict = {}
        for entry in log:
            _update_summary_incremental(incr_summary, entry)

        assert full_summary == incr_summary

    def test_none_gate_not_counted(self):
        """gate_passed=None should count as attempted but not succeeded/failed."""
        summary: dict = {}
        entry = {"model": "m1", "duration_seconds": 30.0, "gate_passed": None, "timestamp": "2026-01-01T00:00:00"}
        _update_summary_incremental(summary, entry)
        s = summary["m1"]
        assert s["total_items_attempted"] == 1
        assert s["total_items_succeeded"] == 0
        assert s["total_items_failed"] == 0
        assert s["success_rate"] == 0.0

    def test_missing_durations_key_migrated(self):
        """If summary has a model entry without _durations, it gets created."""
        summary = {
            "m1": {
                "total_items_attempted": 1,
                "total_items_succeeded": 1,
                "total_items_failed": 0,
                "total_duration_seconds": 50.0,
                "total_retries": 0,
                "average_duration": 50.0,
                "median_duration": 50.0,
                "stddev_duration": 0.0,
                "success_rate": 1.0,
                "last_used": "2026-01-01T00:00:00",
                # Note: no _durations key (old format)
            }
        }
        entry = {"model": "m1", "duration_seconds": 60.0, "gate_passed": True, "timestamp": "2026-01-02T00:00:00"}
        _update_summary_incremental(summary, entry)
        # _durations is created, but only contains the new entry (not historical)
        assert "_durations" in summary["m1"]
        assert 60.0 in summary["m1"]["_durations"]


# ── Migration path (old format) ─────────────────────────────────────


class TestMigrationFromOldFormat:
    def test_old_format_triggers_full_rebuild(self, tmp_path: Path):
        """record_completion on old-format file (no _durations) triggers full rebuild."""
        path = _tmp_stats_path(tmp_path)
        # Write old-format data (summary without _durations)
        old_data = {
            "log": [
                {"model": "m1", "duration_seconds": 50.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            ],
            "summary": {
                "m1": {
                    "total_items_attempted": 1,
                    "total_items_succeeded": 1,
                    "total_items_failed": 0,
                    "total_duration_seconds": 50.0,
                    "total_retries": 0,
                    "average_duration": 50.0,
                    "median_duration": 50.0,
                    "stddev_duration": 0.0,
                    "success_rate": 1.0,
                    "last_used": "2026-01-01T00:00:00",
                }
            },
        }
        path.write_text(json.dumps(old_data), encoding="utf-8")

        # Record a new completion — should trigger migration
        record_completion(_make_record(item_id="B", model="m1", duration=70.0, gate_passed=True), path)

        data = load_model_stats(path)
        assert len(data["log"]) == 2
        # After migration, _durations should be present
        assert "_durations" in data["summary"]["m1"]
        assert data["summary"]["m1"]["total_items_attempted"] == 2

    def test_new_format_uses_incremental(self, tmp_path: Path):
        """record_completion on new-format file (with _durations) uses incremental path."""
        path = _tmp_stats_path(tmp_path)
        # Write new-format data (summary with _durations)
        new_data = {
            "log": [
                {"model": "m1", "duration_seconds": 50.0, "gate_passed": True, "timestamp": "2026-01-01T00:00:00"},
            ],
            "summary": {
                "m1": {
                    "total_items_attempted": 1,
                    "total_items_succeeded": 1,
                    "total_items_failed": 0,
                    "total_duration_seconds": 50.0,
                    "total_retries": 0,
                    "average_duration": 50.0,
                    "median_duration": 50.0,
                    "stddev_duration": 0.0,
                    "success_rate": 1.0,
                    "last_used": "2026-01-01T00:00:00",
                    "_durations": [50.0],
                }
            },
        }
        path.write_text(json.dumps(new_data), encoding="utf-8")

        record_completion(_make_record(item_id="B", model="m1", duration=70.0, gate_passed=False), path)

        data = load_model_stats(path)
        assert len(data["log"]) == 2
        s = data["summary"]["m1"]
        assert s["total_items_attempted"] == 2
        assert s["total_items_succeeded"] == 1
        assert s["total_items_failed"] == 1
        assert s["success_rate"] == 0.5
        assert s["_durations"] == [50.0, 70.0]


# ── get_model_summary strips internal fields ────────────────────────


class TestGetModelSummaryStripsInternals:
    def test_durations_not_exposed(self, tmp_path: Path):
        """get_model_summary should not expose _durations to callers."""
        path = _tmp_stats_path(tmp_path)
        record_completion(_make_record(), path)
        summary = get_model_summary(path)
        for model_stats in summary.values():
            assert "_durations" not in model_stats
