"""Tests for stats.py - session stats formatting, serialization, and persistence."""

import json
from unittest.mock import patch

from pokepoke.stats.stats import (
    _format_duration,
    _print_model_comparison,
    print_stats,
    save_session_stats_to_disk,
    serialize_session_stats,
)
from pokepoke.types import (
    AgentStats,
    BeadsStats,
    BeadsWorkItem,
    MergeQueueStats,
    ModelCompletionRecord,
    SessionStats,
)

# ---------------------------------------------------------------------------
# _format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration:
    """Tests for _format_duration helper."""

    def test_seconds_only(self):
        assert _format_duration(45) == "45s"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "2m 5s"

    def test_hours_minutes_seconds(self):
        assert _format_duration(3661) == "1h 1m 1s"

    def test_zero_seconds(self):
        assert _format_duration(0) == "0s"

    def test_exact_minute(self):
        assert _format_duration(60) == "1m 0s"

    def test_exact_hour(self):
        assert _format_duration(3600) == "1h 0m 0s"

    def test_fractional_seconds_truncated(self):
        assert _format_duration(10.7) == "10s"

    def test_large_duration(self):
        assert _format_duration(7261) == "2h 1m 1s"


# ---------------------------------------------------------------------------
# print_stats (smoke tests - verify no exceptions)
# ---------------------------------------------------------------------------

class TestPrintStats:
    """Tests for print_stats output formatting."""

    def _make_session_stats(self, **kwargs):
        defaults = dict(agent_stats=AgentStats())
        defaults.update(kwargs)
        return SessionStats(**defaults)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_basic_print_stats(self, mock_leaderboard):
        """print_stats should not raise for minimal arguments."""
        print_stats(items_completed=3, total_requests=10, elapsed_seconds=120.0)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_print_stats_with_session_stats(self, mock_leaderboard):
        """print_stats with session_stats should not raise."""
        ss = self._make_session_stats(items_created=2)
        print_stats(items_completed=1, total_requests=5, elapsed_seconds=60.0, session_stats=ss)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_print_stats_with_beads_stats(self, mock_leaderboard):
        """print_stats with beads start/end stats should not raise."""
        ss = self._make_session_stats(
            starting_beads_stats=BeadsStats(total_issues=10, open_issues=5, in_progress_issues=2, closed_issues=3, ready_issues=3),
            ending_beads_stats=BeadsStats(total_issues=12, open_issues=4, in_progress_issues=3, closed_issues=5, ready_issues=2),
        )
        print_stats(items_completed=2, total_requests=8, elapsed_seconds=300.0, session_stats=ss)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_print_stats_with_completed_items(self, mock_leaderboard):
        item = BeadsWorkItem(id="item-1", title="Test", status="closed", priority=1, issue_type="task")
        ss = self._make_session_stats(
            items_completed=1,
            completed_items_list=[item],
        )
        print_stats(items_completed=1, total_requests=3, elapsed_seconds=90.0, session_stats=ss)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_print_stats_with_model_completions(self, mock_leaderboard):
        mc = ModelCompletionRecord(item_id="item-1", model="gpt-4", duration_seconds=30.0, gate_passed=True)
        ss = self._make_session_stats(model_completions=[mc])
        print_stats(items_completed=1, total_requests=2, elapsed_seconds=30.0, session_stats=ss)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_print_stats_zero_completed(self, mock_leaderboard):
        """Should not divide by zero when items_completed is 0."""
        print_stats(items_completed=0, total_requests=0, elapsed_seconds=0.0)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_print_stats_with_agent_stats(self, mock_leaderboard):
        """Session stats with populated agent stats."""
        astats = AgentStats(
            wall_duration=100.0, api_duration=50.0,
            input_tokens=10000, output_tokens=5000,
            lines_added=200, lines_removed=50,
            premium_requests=3,
        )
        ss = self._make_session_stats(agent_stats=astats)
        print_stats(items_completed=1, total_requests=1, elapsed_seconds=100.0, session_stats=ss)

    @patch("pokepoke.models.model_stats_store.print_model_leaderboard")
    def test_print_stats_with_merge_queue(self, mock_leaderboard):
        mqs = MergeQueueStats(
            total_merges=5, successful_merges=4, failed_merges=1,
            merge_durations=[10.0, 20.0], wait_times=[5.0, 8.0],
            queue_depth_samples=[1, 2, 3],
        )
        ss = self._make_session_stats(merge_queue_stats=mqs)
        print_stats(items_completed=4, total_requests=10, elapsed_seconds=500.0, session_stats=ss)


# ---------------------------------------------------------------------------
# _print_model_comparison
# ---------------------------------------------------------------------------

class TestPrintModelComparison:
    """Tests for _print_model_comparison."""

    def test_single_model(self):
        recs = [ModelCompletionRecord(item_id="a", model="gpt-4", duration_seconds=30.0)]
        _print_model_comparison(recs)  # Should not raise

    def test_multiple_models(self):
        recs = [
            ModelCompletionRecord(item_id="a", model="gpt-4", duration_seconds=30.0, gate_passed=True),
            ModelCompletionRecord(item_id="b", model="gpt-4", duration_seconds=45.0, gate_passed=False),
            ModelCompletionRecord(item_id="c", model="claude-3", duration_seconds=20.0, gate_passed=True),
        ]
        _print_model_comparison(recs)  # Should not raise

    def test_empty_list(self):
        _print_model_comparison([])  # Should not raise

    def test_no_gate_results(self):
        recs = [ModelCompletionRecord(item_id="a", model="gpt-4", duration_seconds=30.0, gate_passed=None)]
        _print_model_comparison(recs)  # Should not raise


# ---------------------------------------------------------------------------
# serialize_session_stats
# ---------------------------------------------------------------------------

class TestSerializeSessionStats:
    """Tests for serialize_session_stats."""

    def _make_session_stats(self, **kwargs):
        defaults = dict(agent_stats=AgentStats())
        defaults.update(kwargs)
        return SessionStats(**defaults)

    def test_basic_serialization(self):
        ss = self._make_session_stats()
        data = serialize_session_stats(ss, elapsed_seconds=100.0, items_completed=2, total_requests=5)

        assert data["items_completed"] == 2
        assert data["total_requests"] == 5
        assert data["elapsed_seconds"] == 100.0
        assert "agent_stats" in data
        assert "run_counts" in data

    def test_items_created_and_delta(self):
        ss = self._make_session_stats(items_created=3)
        data = serialize_session_stats(ss, elapsed_seconds=60.0, items_completed=1, total_requests=2)

        assert data["items_created"] == 3
        assert data["net_items_delta"] == 2  # 3 created - 1 completed

    def test_beads_delta_included(self):
        ss = self._make_session_stats(
            starting_beads_stats=BeadsStats(total_issues=10, open_issues=5, in_progress_issues=2, closed_issues=3, ready_issues=3),
            ending_beads_stats=BeadsStats(total_issues=12, open_issues=4, in_progress_issues=3, closed_issues=5, ready_issues=2),
        )
        data = serialize_session_stats(ss, elapsed_seconds=100.0, items_completed=2, total_requests=4)

        assert "beads_start" in data
        assert "beads_end" in data
        assert "beads_delta" in data
        assert data["beads_delta"]["total_issues"] == 2
        assert data["beads_delta"]["closed_issues"] == 2

    def test_no_beads_delta_when_missing(self):
        ss = self._make_session_stats()
        data = serialize_session_stats(ss, elapsed_seconds=10.0, items_completed=0, total_requests=0)

        assert "beads_delta" not in data

    def test_model_completions_serialized(self):
        mc = ModelCompletionRecord(item_id="item-1", model="gpt-4", duration_seconds=30.0, gate_passed=True)
        ss = self._make_session_stats(model_completions=[mc])
        data = serialize_session_stats(ss, elapsed_seconds=30.0, items_completed=1, total_requests=1)

        assert len(data["model_completions"]) == 1
        assert data["model_completions"][0]["item_id"] == "item-1"
        assert data["model_completions"][0]["model"] == "gpt-4"

    def test_merge_queue_included_when_merges_exist(self):
        mqs = MergeQueueStats(total_merges=3, successful_merges=2, failed_merges=1)
        ss = self._make_session_stats(merge_queue_stats=mqs)
        data = serialize_session_stats(ss, elapsed_seconds=50.0, items_completed=2, total_requests=3)

        assert "merge_queue" in data

    def test_merge_queue_excluded_when_no_merges(self):
        ss = self._make_session_stats()
        data = serialize_session_stats(ss, elapsed_seconds=10.0, items_completed=0, total_requests=0)

        assert "merge_queue" not in data

    def test_completed_and_created_items_serialized(self):
        from pokepoke.types import BeadsCreatedItem
        item = BeadsWorkItem(id="item-1", title="Done", status="closed", priority=1, issue_type="task")
        created = BeadsCreatedItem(id="item-2", title="New", agent_type="work")
        ss = self._make_session_stats(
            completed_items_list=[item],
            created_items_list=[created],
        )
        data = serialize_session_stats(ss, elapsed_seconds=10.0, items_completed=1, total_requests=1)

        assert len(data["completed_items"]) == 1
        assert data["completed_items"][0]["id"] == "item-1"
        assert len(data["created_items"]) == 1
        assert data["created_items"][0]["id"] == "item-2"
        assert data["created_items"][0]["agent_type"] == "work"

    def test_output_is_json_serializable(self):
        ss = self._make_session_stats(items_created=1)
        data = serialize_session_stats(ss, elapsed_seconds=42.5, items_completed=1, total_requests=2)
        # Should not raise
        json_str = json.dumps(data)
        assert isinstance(json_str, str)


# ---------------------------------------------------------------------------
# save_session_stats_to_disk
# ---------------------------------------------------------------------------

class TestSaveSessionStatsToDisk:
    """Tests for save_session_stats_to_disk."""

    def test_writes_stats_json(self, tmp_path):
        ss = SessionStats(agent_stats=AgentStats())
        result = save_session_stats_to_disk(
            run_dir=tmp_path, session_stats=ss,
            elapsed_seconds=60.0, items_completed=1, total_requests=2,
        )

        assert result == tmp_path / "stats.json"
        assert result.exists()
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["items_completed"] == 1
        assert data["elapsed_seconds"] == 60.0

    def test_overwrites_existing_stats_json(self, tmp_path):
        (tmp_path / "stats.json").write_text("{}", encoding="utf-8")
        ss = SessionStats(agent_stats=AgentStats(wall_duration=10.0))
        result = save_session_stats_to_disk(
            run_dir=tmp_path, session_stats=ss,
            elapsed_seconds=10.0, items_completed=0, total_requests=0,
        )

        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["agent_stats"]["wall_duration"] == 10.0

    def test_no_temp_file_left_behind(self, tmp_path):
        ss = SessionStats(agent_stats=AgentStats())
        save_session_stats_to_disk(
            run_dir=tmp_path, session_stats=ss,
            elapsed_seconds=0.0, items_completed=0, total_requests=0,
        )
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "stats.json"
