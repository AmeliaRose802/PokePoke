"""Tests for per-model work item completion history logging."""

import json
from datetime import datetime, UTC
from pathlib import Path

from pokepoke.types import AgentStats, BeadsWorkItem, ModelCompletionRecord
from pokepoke.model_history import (
    build_model_history_record,
    append_model_history_entry,
    load_model_history_entries,
)


def _make_item(**overrides) -> BeadsWorkItem:
    base = dict(
        id="PP-1",
        title="Fix bug in module",
        description="",
        status="open",
        priority=1,
        issue_type="bug",
        labels=["backend", "bugfix"],
    )
    base.update(overrides)
    return BeadsWorkItem(**base)


def _make_completion(**overrides) -> ModelCompletionRecord:
    base = dict(
        item_id="PP-1",
        model="gpt-4o",
        duration_seconds=42.0,
        gate_passed=True,
    )
    base.update(overrides)
    return ModelCompletionRecord(**base)


def _make_stats(**overrides) -> AgentStats:
    base = dict(
        wall_duration=100.0,
        api_duration=80.0,
        input_tokens=1000,
        output_tokens=2000,
        lines_added=10,
        lines_removed=5,
        premium_requests=2,
        retries=1,
        tool_calls=3,
    )
    base.update(overrides)
    return AgentStats(**base)


class TestBuildModelHistoryRecord:
    def test_includes_core_fields(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        item = _make_item()
        completion = _make_completion()
        stats = _make_stats()

        record = build_model_history_record(
            item=item,
            model_completion=completion,
            success=True,
            request_count=3,
            gate_runs=2,
            item_stats=stats,
            timestamp=ts,
        )

        assert record["timestamp"].startswith("2026-01-01T12:00:00")
        assert record["model"] == "gpt-4o"
        assert record["work_item_id"] == "PP-1"
        assert record["title"] == item.title
        assert record["issue_type"] == "bug"
        assert record["labels"] == ["backend", "bugfix"]
        assert record["success"] is True
        # 3 total requests → 2 retries
        assert record["retry_attempts"] == 2
        assert record["wall_time_seconds"] == 42.0
        assert record["api_time_seconds"] == 80.0
        assert record["input_tokens"] == 1000
        assert record["output_tokens"] == 2000
        assert record["lines_added"] == 10
        assert record["lines_removed"] == 5
        assert record["quality_gates_ran"] is True
        # gate_runs > 1 so not first-try
        assert record["quality_gates_passed_first_try"] is False

    def test_gate_not_run_sets_null_first_try(self) -> None:
        item = _make_item()
        completion = _make_completion(gate_passed=None)

        record = build_model_history_record(
            item=item,
            model_completion=completion,
            success=True,
            request_count=1,
            gate_runs=0,
            item_stats=None,
        )

        assert record["quality_gates_ran"] is False
        assert record["quality_gates_passed_first_try"] is None
        assert record["api_time_seconds"] is None
        assert record["input_tokens"] is None
        assert record["lines_added"] is None

    def test_gate_passes_first_try(self) -> None:
        item = _make_item()
        completion = _make_completion(gate_passed=True)

        record = build_model_history_record(
            item=item,
            model_completion=completion,
            success=True,
            request_count=1,
            gate_runs=1,
            item_stats=_make_stats(),
        )

        assert record["quality_gates_ran"] is True
        assert record["quality_gates_passed_first_try"] is True

    def test_failure_marks_first_try_false(self) -> None:
        item = _make_item()
        completion = _make_completion(gate_passed=False)

        record = build_model_history_record(
            item=item,
            model_completion=completion,
            success=False,
            request_count=1,
            gate_runs=1,
            item_stats=_make_stats(),
        )

        assert record["success"] is False
        assert record["quality_gates_passed_first_try"] is False


class TestAppendModelHistoryEntry:
    def test_appends_json_lines(self, tmp_path: Path) -> None:
        history_path = tmp_path / "model_history.jsonl"
        item1 = _make_item(id="PP-1")
        item2 = _make_item(id="PP-2")
        completion1 = _make_completion(item_id="PP-1")
        completion2 = _make_completion(item_id="PP-2")
        stats = _make_stats()

        append_model_history_entry(
            item=item1,
            model_completion=completion1,
            success=True,
            request_count=1,
            gate_runs=1,
            item_stats=stats,
            path=history_path,
        )

        append_model_history_entry(
            item=item2,
            model_completion=completion2,
            success=False,
            request_count=2,
            gate_runs=0,
            item_stats=None,
            path=history_path,
        )

        assert history_path.exists()
        lines = history_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

        rec1 = json.loads(lines[0])
        rec2 = json.loads(lines[1])

        assert rec1["work_item_id"] == "PP-1"
        assert rec1["success"] is True
        assert rec2["work_item_id"] == "PP-2"
        assert rec2["retry_attempts"] == 1  # 2 requests → 1 retry


class TestLoadModelHistoryEntries:
    def test_returns_empty_list_when_file_missing(self, tmp_path: Path) -> None:
        history_path = tmp_path / "model_history.jsonl"
        result = load_model_history_entries(path=history_path)
        assert result == []

    def test_loads_entries_from_jsonl(self, tmp_path: Path) -> None:
        history_path = tmp_path / "model_history.jsonl"
        item1 = _make_item(id="PP-1", labels=["backend"])
        item2 = _make_item(id="PP-2", labels=["frontend", "ui"])
        completion1 = _make_completion(item_id="PP-1")
        completion2 = _make_completion(item_id="PP-2")

        append_model_history_entry(
            item=item1,
            model_completion=completion1,
            success=True,
            request_count=1,
            gate_runs=1,
            item_stats=_make_stats(),
            path=history_path,
        )

        append_model_history_entry(
            item=item2,
            model_completion=completion2,
            success=True,
            request_count=1,
            gate_runs=1,
            item_stats=_make_stats(),
            path=history_path,
        )

        result = load_model_history_entries(path=history_path)
        assert len(result) == 2
        assert result[0]["work_item_id"] == "PP-1"
        assert result[0]["labels"] == ["backend"]
        assert result[1]["work_item_id"] == "PP-2"
        assert result[1]["labels"] == ["frontend", "ui"]

    def test_respects_limit(self, tmp_path: Path) -> None:
        history_path = tmp_path / "model_history.jsonl"

        # Create 5 entries
        for i in range(5):
            item = _make_item(id=f"PP-{i}")
            completion = _make_completion(item_id=f"PP-{i}")
            append_model_history_entry(
                item=item,
                model_completion=completion,
                success=True,
                request_count=1,
                gate_runs=1,
                item_stats=None,
                path=history_path,
            )

        # Load only last 2
        result = load_model_history_entries(path=history_path, limit=2)
        assert len(result) == 2
        assert result[0]["work_item_id"] == "PP-3"
        assert result[1]["work_item_id"] == "PP-4"

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        history_path = tmp_path / "model_history.jsonl"

        # Write one valid entry
        item = _make_item(id="PP-1")
        completion = _make_completion(item_id="PP-1")
        append_model_history_entry(
            item=item,
            model_completion=completion,
            success=True,
            request_count=1,
            gate_runs=1,
            item_stats=None,
            path=history_path,
        )

        # Append malformed JSON
        with history_path.open("a", encoding="utf-8") as f:
            f.write("{ invalid json\n")
            f.write("\n")  # blank line

        result = load_model_history_entries(path=history_path)
        # Should only get the valid entry
        assert len(result) == 1
        assert result[0]["work_item_id"] == "PP-1"

    def test_returns_empty_on_os_error(self, tmp_path: Path) -> None:
        """Covers lines 155-157: OSError when file disappears mid-read."""
        history_path = tmp_path / "model_history.jsonl"
        # Create file, then make open() raise OSError
        history_path.write_text('{"work_item_id": "PP-1"}\n', encoding="utf-8")

        from unittest.mock import patch
        with patch.object(Path, 'open', side_effect=OSError("Permission denied")):
            result = load_model_history_entries(path=history_path)
        assert result == []

    def test_repo_name_filters_before_limit(self, tmp_path: Path) -> None:
        """Regression: limit must apply *after* repo_name filtering.

        Previously the limit was applied first, so a repo with entries only
        beyond the global limit window would return zero results.
        """
        history_path = tmp_path / "model_history.jsonl"
        lines: list[str] = []
        # Write 10 entries for RepoA, then 10 for RepoB
        for i in range(10):
            lines.append(json.dumps({"work_item_id": f"A-{i}", "repo_name": "RepoA"}))
        for i in range(10):
            lines.append(json.dumps({"work_item_id": f"B-{i}", "repo_name": "RepoB"}))
        history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # With limit=5 and repo_name="RepoA", we should get 5 RepoA entries
        # even though RepoA entries are in the first half of the file.
        result = load_model_history_entries(path=history_path, limit=5, repo_name="RepoA")
        assert len(result) == 5
        assert all(e["repo_name"] == "RepoA" for e in result)

    def test_repo_name_returns_all_when_under_limit(self, tmp_path: Path) -> None:
        history_path = tmp_path / "model_history.jsonl"
        lines = [
            json.dumps({"work_item_id": "A-0", "repo_name": "RepoA"}),
            json.dumps({"work_item_id": "B-0", "repo_name": "RepoB"}),
            json.dumps({"work_item_id": "A-1", "repo_name": "RepoA"}),
        ]
        history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = load_model_history_entries(path=history_path, limit=200, repo_name="RepoA")
        assert len(result) == 2
        assert result[0]["work_item_id"] == "A-0"
        assert result[1]["work_item_id"] == "A-1"

    def test_repo_name_empty_returns_all_repos(self, tmp_path: Path) -> None:
        history_path = tmp_path / "model_history.jsonl"
        lines = [
            json.dumps({"work_item_id": "A-0", "repo_name": "RepoA"}),
            json.dumps({"work_item_id": "B-0", "repo_name": "RepoB"}),
        ]
        history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = load_model_history_entries(path=history_path, limit=200, repo_name="")
        assert len(result) == 2
