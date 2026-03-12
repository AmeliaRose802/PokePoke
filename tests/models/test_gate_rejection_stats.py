"""Tests for per-gate-model rejection rate tracking.

Covers:
- record_gate_check: recording gate pass/fail per gate model
- load_gate_stats / save_gate_stats: persistence
- get_gate_rejection_stats: read-only summary access
- print_gate_rejection_leaderboard: human-readable output
- _rebuild_gate_summary: summary recomputation from log
- _update_gate_summary_incremental: incremental summary updates
- _format_trend: trend visualization
- gate_model field on ModelCompletionRecord
"""

import json
from pathlib import Path

from pokepoke.types import ModelCompletionRecord
from pokepoke.gate_rejection_tracker import (
    load_gate_stats,
    save_gate_stats,
    record_gate_check,
    get_gate_rejection_stats,
    print_gate_rejection_leaderboard,
    _rebuild_gate_summary,
    _update_gate_summary_incremental,
    _empty_gate_store,
    _format_trend,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _tmp_gate_path(tmp_path: Path) -> Path:
    """Return a temporary gate_rejection_stats.json path."""
    return tmp_path / "gate_rejection_stats.json"


# ── ModelCompletionRecord gate_model field ───────────────────────────


class TestModelCompletionRecordGateModel:
    """Verify the gate_model field on ModelCompletionRecord."""

    def test_default_none(self):
        rec = ModelCompletionRecord(item_id="X", model="m", duration_seconds=1.0)
        assert rec.gate_model is None

    def test_explicit_value(self):
        rec = ModelCompletionRecord(
            item_id="X", model="work-model", duration_seconds=1.0,
            gate_model="gate-model-abc",
        )
        assert rec.gate_model == "gate-model-abc"


# ── _empty_gate_store ────────────────────────────────────────────────


class TestEmptyGateStore:

    def test_structure(self):
        store = _empty_gate_store()
        assert store == {"log": [], "summary": {}}

    def test_independent_copies(self):
        a = _empty_gate_store()
        b = _empty_gate_store()
        a["log"].append("x")
        assert b["log"] == []


# ── load_gate_stats ──────────────────────────────────────────────────


class TestLoadGateStats:

    def test_missing_file(self, tmp_path):
        result = load_gate_stats(tmp_path / "nope.json")
        assert result == _empty_gate_store()

    def test_corrupt_json(self, tmp_path):
        p = _tmp_gate_path(tmp_path)
        p.write_text("not json", encoding="utf-8")
        result = load_gate_stats(p)
        assert result == _empty_gate_store()

    def test_missing_log_key(self, tmp_path):
        p = _tmp_gate_path(tmp_path)
        p.write_text('{"summary": {}}', encoding="utf-8")
        result = load_gate_stats(p)
        assert result == _empty_gate_store()

    def test_valid_file(self, tmp_path):
        p = _tmp_gate_path(tmp_path)
        data = {"log": [{"gate_model": "m1", "passed": True}], "summary": {}}
        p.write_text(json.dumps(data), encoding="utf-8")
        result = load_gate_stats(p)
        assert len(result["log"]) == 1
        assert result["log"][0]["gate_model"] == "m1"


# ── save_gate_stats ──────────────────────────────────────────────────


class TestSaveGateStats:

    def test_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "sub" / "dir" / "gate_stats.json"
        save_gate_stats({"log": [], "summary": {}}, p)
        assert p.exists()

    def test_round_trip(self, tmp_path):
        p = _tmp_gate_path(tmp_path)
        data = {"log": [{"gate_model": "m1", "passed": True}], "summary": {"m1": {"total_checks": 1}}}
        save_gate_stats(data, p)
        loaded = load_gate_stats(p)
        assert loaded == data


# ── _rebuild_gate_summary ────────────────────────────────────────────


class TestRebuildGateSummary:

    def test_empty_log(self):
        assert _rebuild_gate_summary([]) == {}

    def test_single_pass(self):
        log = [{"gate_model": "m1", "passed": True, "timestamp": "2025-01-01T00:00:00"}]
        result = _rebuild_gate_summary(log)
        assert "m1" in result
        assert result["m1"]["total_checks"] == 1
        assert result["m1"]["total_passed"] == 1
        assert result["m1"]["total_rejected"] == 0
        assert result["m1"]["rejection_rate"] == 0.0

    def test_single_rejection(self):
        log = [{"gate_model": "m1", "passed": False, "timestamp": "2025-01-01T00:00:00"}]
        result = _rebuild_gate_summary(log)
        assert result["m1"]["total_rejected"] == 1
        assert result["m1"]["rejection_rate"] == 1.0

    def test_mixed_results(self):
        log = [
            {"gate_model": "m1", "passed": True, "timestamp": "2025-01-01T00:00:00"},
            {"gate_model": "m1", "passed": False, "timestamp": "2025-01-02T00:00:00"},
            {"gate_model": "m1", "passed": True, "timestamp": "2025-01-03T00:00:00"},
            {"gate_model": "m1", "passed": False, "timestamp": "2025-01-04T00:00:00"},
        ]
        result = _rebuild_gate_summary(log)
        assert result["m1"]["total_checks"] == 4
        assert result["m1"]["total_passed"] == 2
        assert result["m1"]["total_rejected"] == 2
        assert result["m1"]["rejection_rate"] == 0.5

    def test_multiple_models(self):
        log = [
            {"gate_model": "strict-model", "passed": False, "timestamp": "2025-01-01T00:00:00"},
            {"gate_model": "strict-model", "passed": False, "timestamp": "2025-01-02T00:00:00"},
            {"gate_model": "lenient-model", "passed": True, "timestamp": "2025-01-01T00:00:00"},
            {"gate_model": "lenient-model", "passed": True, "timestamp": "2025-01-02T00:00:00"},
        ]
        result = _rebuild_gate_summary(log)
        assert result["strict-model"]["rejection_rate"] == 1.0
        assert result["lenient-model"]["rejection_rate"] == 0.0

    def test_last_used_tracks_latest(self):
        log = [
            {"gate_model": "m1", "passed": True, "timestamp": "2025-01-01T00:00:00"},
            {"gate_model": "m1", "passed": True, "timestamp": "2025-06-15T12:00:00"},
        ]
        result = _rebuild_gate_summary(log)
        assert result["m1"]["last_used"] == "2025-06-15T12:00:00"

    def test_trend_capped_at_50(self):
        log = [
            {"gate_model": "m1", "passed": True, "timestamp": f"2025-01-{i+1:02d}T00:00:00"}
            for i in range(60)
        ]
        result = _rebuild_gate_summary(log)
        assert len(result["m1"]["trend"]) == 50


# ── _update_gate_summary_incremental ─────────────────────────────────


class TestUpdateGateSummaryIncremental:

    def test_new_model(self):
        summary: dict = {}
        entry = {"gate_model": "new-model", "passed": True, "timestamp": "2025-01-01T00:00:00"}
        _update_gate_summary_incremental(summary, entry)
        assert "new-model" in summary
        assert summary["new-model"]["total_checks"] == 1
        assert summary["new-model"]["total_passed"] == 1
        assert summary["new-model"]["rejection_rate"] == 0.0

    def test_existing_model_rejection(self):
        summary = {
            "m1": {
                "total_checks": 3,
                "total_passed": 2,
                "total_rejected": 1,
                "rejection_rate": 0.3333,
                "last_used": "2025-01-01T00:00:00",
                "trend": [],
            }
        }
        entry = {"gate_model": "m1", "passed": False, "timestamp": "2025-02-01T00:00:00"}
        _update_gate_summary_incremental(summary, entry)
        assert summary["m1"]["total_checks"] == 4
        assert summary["m1"]["total_rejected"] == 2
        assert summary["m1"]["rejection_rate"] == 0.5

    def test_trend_appended(self):
        summary = {
            "m1": {
                "total_checks": 0, "total_passed": 0, "total_rejected": 0,
                "rejection_rate": 0.0, "last_used": "", "trend": [],
            }
        }
        for i in range(55):
            entry = {"gate_model": "m1", "passed": i % 2 == 0, "timestamp": f"ts-{i}"}
            _update_gate_summary_incremental(summary, entry)
        # Trend should be capped at 50
        assert len(summary["m1"]["trend"]) == 50


# ── record_gate_check ────────────────────────────────────────────────


class TestRecordGateCheck:

    def test_records_pass(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pokepoke.metrics_context.get_current_repo_name", lambda: "test-repo")
        p = _tmp_gate_path(tmp_path)
        record_gate_check("gate-model-a", "PP-1", True, path=p)
        data = load_gate_stats(p)
        assert len(data["log"]) == 1
        assert data["log"][0]["passed"] is True
        assert data["log"][0]["gate_model"] == "gate-model-a"
        assert data["summary"]["gate-model-a"]["total_passed"] == 1

    def test_records_rejection(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pokepoke.metrics_context.get_current_repo_name", lambda: "test-repo")
        p = _tmp_gate_path(tmp_path)
        record_gate_check("gate-model-a", "PP-1", False, path=p)
        data = load_gate_stats(p)
        assert data["log"][0]["passed"] is False
        assert data["summary"]["gate-model-a"]["total_rejected"] == 1
        assert data["summary"]["gate-model-a"]["rejection_rate"] == 1.0

    def test_multiple_records_accumulate(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pokepoke.metrics_context.get_current_repo_name", lambda: "test-repo")
        p = _tmp_gate_path(tmp_path)
        record_gate_check("m1", "PP-1", True, path=p)
        record_gate_check("m1", "PP-2", False, path=p)
        record_gate_check("m1", "PP-3", True, path=p)
        data = load_gate_stats(p)
        assert len(data["log"]) == 3
        s = data["summary"]["m1"]
        assert s["total_checks"] == 3
        assert s["total_passed"] == 2
        assert s["total_rejected"] == 1
        assert abs(s["rejection_rate"] - 0.3333) < 0.01

    def test_multiple_models_tracked(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pokepoke.metrics_context.get_current_repo_name", lambda: "test-repo")
        p = _tmp_gate_path(tmp_path)
        record_gate_check("strict", "PP-1", False, path=p)
        record_gate_check("lenient", "PP-2", True, path=p)
        data = load_gate_stats(p)
        assert "strict" in data["summary"]
        assert "lenient" in data["summary"]
        assert data["summary"]["strict"]["rejection_rate"] == 1.0
        assert data["summary"]["lenient"]["rejection_rate"] == 0.0


# ── get_gate_rejection_stats ─────────────────────────────────────────


class TestGetGateRejectionStats:

    def test_empty_when_no_file(self, tmp_path):
        result = get_gate_rejection_stats(tmp_path / "nope.json")
        assert result == {}

    def test_returns_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pokepoke.metrics_context.get_current_repo_name", lambda: "test-repo")
        p = _tmp_gate_path(tmp_path)
        record_gate_check("m1", "PP-1", True, path=p)
        record_gate_check("m1", "PP-2", False, path=p)
        stats = get_gate_rejection_stats(p)
        assert "m1" in stats
        assert stats["m1"]["total_checks"] == 2
        assert stats["m1"]["rejection_rate"] == 0.5


# ── print_gate_rejection_leaderboard ─────────────────────────────────


class TestPrintGateRejectionLeaderboard:

    def test_no_data_no_output(self, tmp_path, capsys):
        print_gate_rejection_leaderboard(tmp_path / "nope.json")
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_prints_report(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr("pokepoke.metrics_context.get_current_repo_name", lambda: "test-repo")
        p = _tmp_gate_path(tmp_path)
        record_gate_check("model-alpha", "PP-1", True, path=p)
        record_gate_check("model-alpha", "PP-2", False, path=p)
        record_gate_check("model-beta", "PP-3", True, path=p)
        print_gate_rejection_leaderboard(p)
        captured = capsys.readouterr()
        assert "Gate Agent Rejection Rates" in captured.out
        assert "model-alpha" in captured.out
        assert "model-beta" in captured.out
        assert "50%" in captured.out  # model-alpha rejection rate
        assert "0%" in captured.out   # model-beta rejection rate


# ── _format_trend ────────────────────────────────────────────────────


class TestFormatTrend:

    def test_empty(self):
        assert _format_trend([]) == ""

    def test_all_pass(self):
        data = [{"passed": True}] * 5
        assert _format_trend(data) == "✓✓✓✓✓"

    def test_all_reject(self):
        data = [{"passed": False}] * 3
        assert _format_trend(data) == "✗✗✗"

    def test_mixed(self):
        data = [{"passed": True}, {"passed": False}, {"passed": True}]
        assert _format_trend(data) == "✓✗✓"

    def test_capped_at_max_markers(self):
        data = [{"passed": True}] * 30
        result = _format_trend(data, max_markers=10)
        assert len(result) == 10
