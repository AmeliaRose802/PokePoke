"""Tests for fresh vs resumed gate session tracking."""

from pathlib import Path

from pokepoke.stats.gate_session_tracker import (
    GateSessionCheck,
    _empty_gate_session_store,
    get_gate_session_stats,
    load_gate_session_stats,
    print_gate_session_leaderboard,
    record_gate_session_check,
    save_gate_session_stats,
)


def _tmp_gate_session_path(tmp_path: Path) -> Path:
    return tmp_path / "gate_session_stats.json"


class TestGateSessionStore:
    def test_empty_store_shape(self):
        assert _empty_gate_session_store() == {"log": [], "summary": {}}

    def test_record_fresh_and_resumed_runs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pokepoke.stats.metrics_context.get_current_repo_name",
            lambda default="": "repo-a",
        )
        p = _tmp_gate_session_path(tmp_path)
        record_gate_session_check(
            GateSessionCheck(
                gate_model="gate-model-a",
                item_id="PP-1",
                passed=True,
                resumed=False,
                input_tokens=100,
                output_tokens=50,
            ),
            p,
        )
        record_gate_session_check(
            GateSessionCheck(
                gate_model="gate-model-a",
                item_id="PP-2",
                passed=False,
                resumed=True,
                input_tokens=200,
                output_tokens=75,
            ),
            p,
        )

        data = load_gate_session_stats(p)
        assert len(data["log"]) == 2
        assert data["log"][0]["variant"] == "fresh"
        assert data["log"][1]["variant"] == "resumed"

        summary = get_gate_session_stats(p)
        assert summary["fresh"]["total_runs"] == 1
        assert summary["fresh"]["pass_rate"] == 1.0
        assert summary["fresh"]["average_input_tokens"] == 100.0
        assert summary["resumed"]["total_runs"] == 1
        assert summary["resumed"]["pass_rate"] == 0.0
        assert summary["resumed"]["average_output_tokens"] == 75.0

    def test_round_trip_save(self, tmp_path):
        p = _tmp_gate_session_path(tmp_path)
        data = {
            "log": [{"variant": "fresh", "passed": True, "input_tokens": 10, "output_tokens": 5}],
            "summary": {
                "fresh": {
                    "total_runs": 1,
                    "total_passed": 1,
                    "total_failed": 0,
                    "total_input_tokens": 10,
                    "total_output_tokens": 5,
                    "average_input_tokens": 10.0,
                    "average_output_tokens": 5.0,
                    "pass_rate": 1.0,
                    "last_used": "2025-01-01T00:00:00",
                }
            },
        }
        save_gate_session_stats(data, p)
        assert load_gate_session_stats(p) == data

    def test_print_gate_session_leaderboard(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setattr(
            "pokepoke.stats.metrics_context.get_current_repo_name",
            lambda default="": "repo-a",
        )
        p = _tmp_gate_session_path(tmp_path)
        record_gate_session_check(
            GateSessionCheck(
                gate_model="gate-model-a",
                item_id="PP-1",
                passed=True,
                resumed=False,
            ),
            p,
        )
        record_gate_session_check(
            GateSessionCheck(
                gate_model="gate-model-a",
                item_id="PP-2",
                passed=False,
                resumed=True,
            ),
            p,
        )

        with caplog.at_level("INFO", logger="pokepoke.stats.gate_session_tracker"):
            print_gate_session_leaderboard(p)

        assert "Fresh" in caplog.text
        assert "Resumed" in caplog.text
