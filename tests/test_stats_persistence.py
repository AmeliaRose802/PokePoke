"""Tests for session stats persistence to disk."""

import json
import tempfile
from pathlib import Path

import pytest

from pokepoke.types import (
    AgentStats,
    BeadsStats,
    BeadsWorkItem,
    ModelCompletionRecord,
    SessionStats,
)
from pokepoke.stats import save_session_stats_to_disk, serialize_session_stats
from pokepoke.logging_utils import RunLogger


# ── Helpers ──────────────────────────────────────────────────────────

def _make_session_stats(**overrides) -> SessionStats:
    """Build a SessionStats with sensible defaults; override any field via kwargs."""
    defaults = dict(
        agent_stats=AgentStats(
            wall_duration=120.5,
            api_duration=45.3,
            input_tokens=5000,
            output_tokens=3000,
            lines_added=42,
            lines_removed=10,
            premium_requests=3,
            retries=1,
            tool_calls=12,
        ),
        items_completed=2,
        work_agent_runs=3,
        gate_agent_runs=2,
        tech_debt_agent_runs=1,
        janitor_agent_runs=0,
        janitor_lines_removed=0,
        backlog_cleanup_agent_runs=0,
        cleanup_agent_runs=1,
        beta_tester_agent_runs=0,
        code_review_agent_runs=0,
        worktree_cleanup_agent_runs=0,
        completed_items_list=[
            BeadsWorkItem(id="PP-1", title="First item", status="closed", priority=1, issue_type="bug"),
            BeadsWorkItem(id="PP-2", title="Second item", status="closed", priority=2, issue_type="task"),
        ],
        model_completions=[
            ModelCompletionRecord(item_id="PP-1", model="gpt-4o", duration_seconds=55.2, gate_passed=True),
            ModelCompletionRecord(item_id="PP-2", model="claude-sonnet", duration_seconds=62.8, gate_passed=False),
        ],
        starting_beads_stats=BeadsStats(total_issues=10, open_issues=5, in_progress_issues=2, closed_issues=3, ready_issues=4),
        ending_beads_stats=BeadsStats(total_issues=12, open_issues=4, in_progress_issues=1, closed_issues=7, ready_issues=3),
    )
    defaults.update(overrides)
    return SessionStats(**defaults)


# ── serialize_session_stats ──────────────────────────────────────────

class TestSerializeSessionStats:
    """Tests for the serialize_session_stats function."""

    def test_basic_fields(self):
        stats = _make_session_stats()
        data = serialize_session_stats(stats, elapsed_seconds=300.0, items_completed=2, total_requests=5)

        assert data["items_completed"] == 2
        assert data["total_requests"] == 5
        assert data["elapsed_seconds"] == 300.0

    def test_agent_stats_included(self):
        stats = _make_session_stats()
        data = serialize_session_stats(stats, 100.0, 1, 1)

        agent = data["agent_stats"]
        assert agent["wall_duration"] == 120.5
        assert agent["api_duration"] == 45.3
        assert agent["input_tokens"] == 5000
        assert agent["output_tokens"] == 3000
        assert agent["lines_added"] == 42
        assert agent["lines_removed"] == 10
        assert agent["premium_requests"] == 3
        assert agent["retries"] == 1
        assert agent["tool_calls"] == 12

    def test_run_counts_included(self):
        stats = _make_session_stats()
        data = serialize_session_stats(stats, 100.0, 1, 1)

        rc = data["run_counts"]
        assert rc["work_agent"] == 3
        assert rc["gate_agent"] == 2
        assert rc["tech_debt_agent"] == 1
        assert rc["cleanup_agent"] == 1

    def test_completed_items_included(self):
        stats = _make_session_stats()
        data = serialize_session_stats(stats, 100.0, 2, 3)

        items = data["completed_items"]
        assert len(items) == 2
        assert items[0] == {"id": "PP-1", "title": "First item"}
        assert items[1] == {"id": "PP-2", "title": "Second item"}

    def test_model_completions_included(self):
        stats = _make_session_stats()
        data = serialize_session_stats(stats, 100.0, 2, 3)

        mc = data["model_completions"]
        assert len(mc) == 2
        assert mc[0]["item_id"] == "PP-1"
        assert mc[0]["model"] == "gpt-4o"
        assert mc[0]["gate_passed"] is True
        assert mc[1]["model"] == "claude-sonnet"
        assert mc[1]["gate_passed"] is False

    def test_beads_delta_computed(self):
        stats = _make_session_stats()
        data = serialize_session_stats(stats, 100.0, 2, 3)

        assert "beads_start" in data
        assert "beads_end" in data
        delta = data["beads_delta"]
        assert delta["total_issues"] == 2   # 12 - 10
        assert delta["open_issues"] == -1   # 4 - 5
        assert delta["closed_issues"] == 4  # 7 - 3

    def test_no_beads_stats_omits_delta(self):
        stats = _make_session_stats(starting_beads_stats=None, ending_beads_stats=None)
        data = serialize_session_stats(stats, 100.0, 0, 0)

        assert "beads_start" not in data
        assert "beads_end" not in data
        assert "beads_delta" not in data

    def test_partial_beads_stats_no_delta(self):
        """If only starting or ending stats exist, delta should not be computed."""
        stats = _make_session_stats(ending_beads_stats=None)
        data = serialize_session_stats(stats, 100.0, 0, 0)

        assert "beads_start" in data
        assert "beads_end" not in data
        assert "beads_delta" not in data

    def test_empty_session(self):
        """A session with zero work should still produce valid JSON structure."""
        stats = SessionStats(agent_stats=AgentStats())
        data = serialize_session_stats(stats, 0.0, 0, 0)

        assert data["items_completed"] == 0
        assert data["total_requests"] == 0
        assert data["elapsed_seconds"] == 0.0
        assert data["completed_items"] == []
        assert data["model_completions"] == []

    def test_output_is_json_serializable(self):
        stats = _make_session_stats()
        data = serialize_session_stats(stats, 300.0, 2, 5)

        # Must not raise
        json_str = json.dumps(data)
        roundtripped = json.loads(json_str)
        assert roundtripped == data


# ── save_session_stats_to_disk ───────────────────────────────────────

class TestSaveSessionStatsToDisk:
    """Tests for writing stats.json to disk."""

    def test_creates_stats_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            stats = _make_session_stats()

            result_path = save_session_stats_to_disk(run_dir, stats, 300.0, 2, 5)

            assert result_path == run_dir / "stats.json"
            assert result_path.exists()

    def test_stats_json_is_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            stats = _make_session_stats()

            save_session_stats_to_disk(run_dir, stats, 300.0, 2, 5)

            with open(run_dir / "stats.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            assert data["items_completed"] == 2
            assert data["total_requests"] == 5
            assert len(data["model_completions"]) == 2

    def test_stats_json_has_beads_delta(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            stats = _make_session_stats()

            save_session_stats_to_disk(run_dir, stats, 300.0, 2, 5)

            with open(run_dir / "stats.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            assert "beads_delta" in data
            assert data["beads_delta"]["closed_issues"] == 4


# ── RunLogger.finalize integration ───────────────────────────────────

class TestRunLoggerFinalizePersistsStats:
    """Verify that RunLogger.finalize writes stats.json when session_stats is provided."""

    def test_finalize_with_stats_creates_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)
            stats = _make_session_stats()

            logger.finalize(items_completed=2, total_requests=5, elapsed=300.0, session_stats=stats)

            stats_path = logger.get_run_dir() / "stats.json"
            assert stats_path.exists()

            with open(stats_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            assert data["items_completed"] == 2
            assert data["total_requests"] == 5
            assert len(data["model_completions"]) == 2

    def test_finalize_without_stats_no_json(self):
        """When session_stats is None (backward compat), no stats.json is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)

            logger.finalize(items_completed=0, total_requests=0, elapsed=0.0)

            stats_path = logger.get_run_dir() / "stats.json"
            assert not stats_path.exists()

    def test_finalize_logs_stats_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)
            stats = _make_session_stats()

            logger.finalize(items_completed=1, total_requests=2, elapsed=60.0, session_stats=stats)

            with open(logger.orchestrator_log_path, "r", encoding="utf-8") as f:
                content = f.read()

            assert "stats.json" in content
            assert "Session stats saved" in content
