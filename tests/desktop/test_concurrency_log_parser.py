"""Tests for the concurrency log parser."""
from __future__ import annotations

import tempfile
from pathlib import Path

from pokepoke.desktop.concurrency_log_parser import parse_concurrency_timeline


def _write_log(lines: list[str], tmpdir: str) -> Path:
    """Write log lines to a temporary orchestrator.log."""
    log_path = Path(tmpdir) / "orchestrator.log"
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path


class TestParseConcurrencyTimeline:
    """Tests for parse_concurrency_timeline."""

    def test_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log([], tmpdir)
            result = parse_concurrency_timeline(log_path)
            assert result == {"lifecycle": [], "completions": [], "failures": []}

    def test_missing_file(self) -> None:
        result = parse_concurrency_timeline("/nonexistent/orchestrator.log")
        assert result == {"lifecycle": [], "completions": [], "failures": []}

    def test_lifecycle_entries(self) -> None:
        lines = [
            "[2024-01-15 09:30:00] [DEBUG] [poll #1] Lifecycle: active=2 max=4 slots=2 mem=8192MB rss=150MB",
            "[2024-01-15 09:31:00] [INFO] [poll #50] Lifecycle: active=4 max=4 slots=0 mem=6144MB rss=180MB cpu=32.5%",
            "[2024-01-15 09:32:00] [DEBUG] [poll #51] Lifecycle: active=3 max=8 slots=5 mem=4096MB",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log(lines, tmpdir)
            result = parse_concurrency_timeline(log_path)

        assert len(result["lifecycle"]) == 3
        assert result["lifecycle"][0] == {
            "ts": "2024-01-15 09:30:00",
            "active": 2,
            "max": 4,
            "slots": 2,
            "mem": 8192,
            "rss": 150,
        }
        assert result["lifecycle"][1]["active"] == 4
        assert result["lifecycle"][1]["rss"] == 180
        assert result["lifecycle"][1]["cpu"] == 32.5
        assert result["lifecycle"][2]["max"] == 8
        # Old-format line without rss= should still parse, rss key absent
        assert "rss" not in result["lifecycle"][2]
        assert "cpu" not in result["lifecycle"][2]

    def test_completion_events(self) -> None:
        lines = [
            "[2024-01-15 09:35:00] [INFO] [PokePoke] Worker completed ABC-123",
            "[2024-01-15 09:36:00] [INFO] [PokePoke] \u2705 Agent worker-1 completed item DEF-456",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log(lines, tmpdir)
            result = parse_concurrency_timeline(log_path)

        assert len(result["completions"]) == 2
        assert result["completions"][0] == {"ts": "2024-01-15 09:35:00", "item_id": "ABC-123"}
        assert result["completions"][1] == {"ts": "2024-01-15 09:36:00", "item_id": "DEF-456"}

    def test_failure_events(self) -> None:
        lines = [
            "[2024-01-15 09:35:00] [ERROR] [PokePoke] Worker failed GHI-789: TimeoutError",
            "[2024-01-15 09:36:00] [INFO] [PokePoke] \u274c Agent worker-2 failed item JKL-012",
            "[2024-01-15 09:37:00] [INFO] [PokePoke] \u274c Agent worker-3 raised exception on item MNO-345",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log(lines, tmpdir)
            result = parse_concurrency_timeline(log_path)

        assert len(result["failures"]) == 3
        assert result["failures"][0]["item_id"] == "GHI-789:"
        assert result["failures"][1]["item_id"] == "JKL-012"
        assert result["failures"][2]["item_id"] == "MNO-345"

    def test_mixed_events(self) -> None:
        lines = [
            "[2024-01-15 09:30:00] [DEBUG] [poll #1] Lifecycle: active=1 max=4 slots=3 mem=8192MB rss=120MB",
            "[2024-01-15 09:31:00] [INFO] [PokePoke] Worker completed ITEM-1",
            "[2024-01-15 09:32:00] [DEBUG] [poll #2] Lifecycle: active=2 max=4 slots=2 mem=7168MB rss=125MB",
            "[2024-01-15 09:33:00] [ERROR] [PokePoke] Worker failed ITEM-2: Error",
            "[2024-01-15 09:34:00] [DEBUG] [poll #3] Lifecycle: active=1 max=4 slots=3 mem=6144MB rss=130MB",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log(lines, tmpdir)
            result = parse_concurrency_timeline(log_path)

        assert len(result["lifecycle"]) == 3
        assert len(result["completions"]) == 1
        assert len(result["failures"]) == 1

    def test_deduplicates_events(self) -> None:
        lines = [
            "[2024-01-15 09:35:00] [INFO] [PokePoke] Worker completed ABC-123",
            "[2024-01-15 09:35:00] [INFO] [PokePoke] \u2705 Agent worker-1 completed item ABC-123",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log(lines, tmpdir)
            result = parse_concurrency_timeline(log_path)

        assert len(result["completions"]) == 1
        assert result["completions"][0]["item_id"] == "ABC-123"

    def test_ignores_unrelated_lines(self) -> None:
        lines = [
            "=" * 80,
            "PokePoke Orchestrator Log",
            "=" * 80,
            "Run ID: 20240115_093045_a1b2c3d4",
            "[2024-01-15 09:30:00] [INFO] [PokePoke] Started processing work item: ABC-123",
            "[2024-01-15 09:31:00] [DEBUG] [poll #1] Lifecycle: active=1 max=4 slots=3 mem=8192MB rss=100MB",
            "[2024-01-15 09:32:00] [WARNING] [PokePoke] Memory pressure (512MB) - 1 slot(s)",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log(lines, tmpdir)
            result = parse_concurrency_timeline(log_path)

        assert len(result["lifecycle"]) == 1
        assert result["completions"] == []
        assert result["failures"] == []

    def test_repo_tag_in_lifecycle(self) -> None:
        """Lifecycle entries may have a repo tag before the poll marker."""
        lines = [
            "[2024-01-15 09:30:00] [DEBUG] [PokePoke] [poll #1] Lifecycle: active=3 max=8 slots=5 mem=2048MB rss=200MB",
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = _write_log(lines, tmpdir)
            result = parse_concurrency_timeline(log_path)

        assert len(result["lifecycle"]) == 1
        assert result["lifecycle"][0]["active"] == 3
