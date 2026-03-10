"""Tests for merge queue performance metrics (MergeQueueStats).

Covers:
- MergeQueueStats dataclass computed properties
- MergeQueue instrumentation (timing, counters, queue depth)
- SessionStats integration (record + snapshot)
- stats.py display and serialization
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.merge_queue import MergeQueue, MergeStatus
from pokepoke.stats import serialize_session_stats, _print_merge_queue_stats
from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    MergeQueueStats,
    SessionStats,
)


def _item(item_id: str = "TEST-1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Item {item_id}", status="ready",
        priority=1, issue_type="task",
    )


# ── MergeQueueStats dataclass ─────────────────────────────────────


class TestMergeQueueStatsDefaults:
    """MergeQueueStats should start at zero/empty."""

    def test_default_counters(self):
        s = MergeQueueStats()
        assert s.total_merges == 0
        assert s.successful_merges == 0
        assert s.failed_merges == 0
        assert s.total_rebases == 0
        assert s.successful_rebases == 0
        assert s.failed_rebases == 0
        assert s.high_conflict_merges == 0

    def test_default_lists_empty(self):
        s = MergeQueueStats()
        assert s.merge_durations == []
        assert s.wait_times == []
        assert s.queue_depth_samples == []
        assert s.double_rebase_overhead_seconds == []

    def test_default_computed_properties(self):
        s = MergeQueueStats()
        assert s.avg_merge_duration == 0.0
        assert s.max_merge_duration == 0.0
        assert s.avg_wait_time == 0.0
        assert s.max_wait_time == 0.0
        assert s.max_queue_depth == 0
        assert s.avg_queue_depth == 0.0
        assert s.rebase_success_rate == 0.0
        assert s.avg_double_rebase_overhead == 0.0


class TestMergeQueueStatsComputedProperties:
    """Computed properties should aggregate raw sample lists."""

    def test_avg_and_max_merge_duration(self):
        s = MergeQueueStats(merge_durations=[1.0, 3.0, 5.0])
        assert s.avg_merge_duration == 3.0
        assert s.max_merge_duration == 5.0

    def test_avg_and_max_wait_time(self):
        s = MergeQueueStats(wait_times=[0.5, 1.5, 2.0])
        assert s.avg_wait_time == pytest.approx(4.0 / 3.0, abs=0.01)
        assert s.max_wait_time == 2.0

    def test_queue_depth(self):
        s = MergeQueueStats(queue_depth_samples=[1, 3, 2])
        assert s.max_queue_depth == 3
        assert s.avg_queue_depth == 2.0

    def test_rebase_success_rate(self):
        s = MergeQueueStats(total_rebases=10, successful_rebases=7, failed_rebases=3)
        assert s.rebase_success_rate == 0.7

    def test_double_rebase_overhead(self):
        s = MergeQueueStats(double_rebase_overhead_seconds=[2.0, 4.0])
        assert s.avg_double_rebase_overhead == 3.0


class TestMergeQueueStatsToSummaryDict:
    """to_summary_dict should return a flat, JSON-serialisable dict."""

    def test_empty_stats(self):
        d = MergeQueueStats().to_summary_dict()
        assert d["total_merges"] == 0
        assert d["rebase_success_rate"] == 0.0
        assert isinstance(d, dict)

    def test_populated_stats(self):
        s = MergeQueueStats(
            total_merges=5, successful_merges=4, failed_merges=1,
            total_rebases=6, successful_rebases=5, failed_rebases=1,
            high_conflict_merges=1,
            merge_durations=[2.0, 3.0],
            wait_times=[0.1, 0.2],
            queue_depth_samples=[1, 2],
            double_rebase_overhead_seconds=[1.5],
        )
        d = s.to_summary_dict()
        assert d["total_merges"] == 5
        assert d["successful_merges"] == 4
        assert d["avg_merge_duration_s"] == 2.5
        assert d["max_merge_duration_s"] == 3.0
        assert d["rebase_success_rate"] == pytest.approx(5.0 / 6, abs=0.001)
        assert d["avg_double_rebase_overhead_s"] == 1.5


# ── MergeQueue instrumentation ────────────────────────────────────


class TestMergeQueueStatsCollection:
    """Verify MergeQueue collects metrics during operation."""

    def setup_method(self):
        self.queue = MergeQueue()

    def teardown_method(self):
        if self.queue.is_running:
            self.queue.shutdown(timeout=5)

    def test_submit_records_queue_depth(self):
        """Each submit should sample queue depth."""
        with patch.object(self.queue, "_queue") as mock_q:
            mock_q.qsize.return_value = 3
            # Don't actually start worker
            self.queue._started = True
            self.queue._worker = MagicMock(is_alive=MagicMock(return_value=True))
            self.queue.submit(Path("/fake"), _item("D-1"))
            assert self.queue._stats.queue_depth_samples == [3]

    def test_stats_property_returns_copy(self):
        """stats property should return a copy, not the internal object."""
        self.queue._stats.total_merges = 42
        snap = self.queue.stats
        assert snap.total_merges == 42
        snap.total_merges = 0
        assert self.queue._stats.total_merges == 42

    def test_reset_stats_clears_counters(self):
        """reset_stats should zero all counters and clear sample lists."""
        self.queue._stats.total_merges = 5
        self.queue._stats.successful_merges = 3
        self.queue._stats.failed_merges = 2
        self.queue._stats.merge_durations = [1.0, 2.0]
        self.queue._stats.wait_times = [0.5]
        self.queue._stats.queue_depth_samples = [1, 2, 3]
        self.queue.reset_stats()
        s = self.queue.stats
        assert s.total_merges == 0
        assert s.successful_merges == 0
        assert s.failed_merges == 0
        assert s.merge_durations == []
        assert s.wait_times == []
        assert s.queue_depth_samples == []

    def test_reset_stats_does_not_affect_prior_snapshot(self):
        """A snapshot taken before reset should retain its values."""
        self.queue._stats.total_merges = 7
        snap = self.queue.stats
        self.queue.reset_stats()
        assert snap.total_merges == 7
        assert self.queue.stats.total_merges == 0

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_successful_merge_records_metrics(
        self, mock_rebase, mock_branch, mock_conflict, mock_shutdown, tmp_path
    ):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("M-1"))
            result = future.result(timeout=10)

        assert result.status == MergeStatus.SUCCESS
        s = self.queue.stats
        assert s.total_merges == 1
        assert s.successful_merges == 1
        assert s.failed_merges == 0
        assert len(s.merge_durations) == 1
        assert s.merge_durations[0] >= 0
        assert len(s.wait_times) == 1
        assert s.wait_times[0] >= 0
        assert s.total_rebases == 1
        assert s.successful_rebases == 1

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_failed_merge_records_metrics(
        self, mock_rebase, mock_branch, mock_conflict, mock_shutdown, tmp_path
    ):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=False
        ):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("F-1"))
            result = future.result(timeout=10)

        assert result.status == MergeStatus.FAILED
        s = self.queue.stats
        assert s.total_merges == 1
        assert s.successful_merges == 0
        assert s.failed_merges == 1

    @patch("pokepoke.merge_queue.time.sleep")
    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue.is_high_conflict_risk", return_value=True)
    @patch("pokepoke.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_high_conflict_records_double_rebase(
        self, mock_rebase, mock_branch, mock_conflict, mock_shutdown, mock_sleep, tmp_path
    ):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("HC-1"))
            result = future.result(timeout=10)

        assert result.status == MergeStatus.SUCCESS
        s = self.queue.stats
        assert s.high_conflict_merges == 1
        assert s.total_rebases == 2
        assert s.successful_rebases == 2
        assert len(s.double_rebase_overhead_seconds) == 1
        assert s.double_rebase_overhead_seconds[0] >= 0

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.merge_queue.is_worktree_clean", return_value=True)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=False)
    def test_rebase_failure_records_failed_rebase(
        self, mock_rebase, mock_clean, mock_branch, mock_conflict, mock_shutdown, tmp_path
    ):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("RF-1"))
            future.result(timeout=10)

        s = self.queue.stats
        assert s.total_rebases == 1
        assert s.failed_rebases == 1
        assert s.successful_rebases == 0

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.merge_queue.get_default_branch", side_effect=RuntimeError("boom"))
    def test_exception_still_records_merge_failure(
        self, mock_branch, mock_conflict, mock_shutdown, tmp_path
    ):
        self.queue.start()
        future = self.queue.submit(tmp_path, _item("EX-1"))
        result = future.result(timeout=10)

        assert result.status == MergeStatus.FAILED
        s = self.queue.stats
        assert s.total_merges == 1
        assert s.failed_merges == 1

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_multiple_merges_accumulate(
        self, mock_rebase, mock_branch, mock_conflict, mock_shutdown, tmp_path
    ):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            for i in range(3):
                future = self.queue.submit(tmp_path, _item(f"ACC-{i}"))
                future.result(timeout=10)

        s = self.queue.stats
        assert s.total_merges == 3
        assert s.successful_merges == 3
        assert len(s.merge_durations) == 3
        assert len(s.wait_times) == 3
        assert len(s.queue_depth_samples) == 3


# ── SessionStats integration ──────────────────────────────────────


class TestSessionStatsMergeQueueIntegration:
    """MergeQueueStats wired into SessionStats and snapshot."""

    def test_default_merge_queue_stats(self):
        ss = SessionStats(agent_stats=AgentStats())
        assert ss.merge_queue_stats.total_merges == 0

    def test_record_merge_queue_stats(self):
        ss = SessionStats(agent_stats=AgentStats())
        mqs = MergeQueueStats(
            total_merges=5, successful_merges=4, failed_merges=1,
            merge_durations=[1.0, 2.0], wait_times=[0.1],
            queue_depth_samples=[2, 3],
        )
        ss.record_merge_queue_stats(mqs)
        assert ss.merge_queue_stats.total_merges == 5
        assert ss.merge_queue_stats.successful_merges == 4
        assert ss.merge_queue_stats.merge_durations == [1.0, 2.0]

    def test_record_copies_data(self):
        """record_merge_queue_stats should copy, not alias."""
        ss = SessionStats(agent_stats=AgentStats())
        mqs = MergeQueueStats(merge_durations=[1.0])
        ss.record_merge_queue_stats(mqs)
        mqs.merge_durations.append(999.0)
        assert 999.0 not in ss.merge_queue_stats.merge_durations

    def test_snapshot_includes_merge_queue_stats(self):
        ss = SessionStats(agent_stats=AgentStats())
        ss.merge_queue_stats = MergeQueueStats(
            total_merges=3, successful_merges=2, failed_merges=1,
            merge_durations=[1.0, 2.0, 3.0],
            queue_depth_samples=[1, 2],
        )
        snap = ss.snapshot()
        assert snap.merge_queue_stats.total_merges == 3
        assert snap.merge_queue_stats.avg_merge_duration == 2.0

    def test_snapshot_merge_queue_stats_is_copy(self):
        """Snapshot should not alias internal lists."""
        ss = SessionStats(agent_stats=AgentStats())
        ss.merge_queue_stats = MergeQueueStats(merge_durations=[1.0])
        snap = ss.snapshot()
        ss.merge_queue_stats.merge_durations.append(99.0)
        assert 99.0 not in snap.merge_queue_stats.merge_durations


# ── stats.py display and serialization ─────────────────────────────


class TestPrintMergeQueueStats:
    """_print_merge_queue_stats display output."""

    def test_prints_basic_counters(self, capsys):
        mqs = MergeQueueStats(
            total_merges=10, successful_merges=8, failed_merges=2,
            total_rebases=12, successful_rebases=10, failed_rebases=2,
            merge_durations=[2.0, 3.0], wait_times=[0.5, 1.0],
            queue_depth_samples=[1, 3, 2],
        )
        _print_merge_queue_stats(mqs)
        out = capsys.readouterr().out
        assert "Total merges:" in out
        assert "10" in out
        assert "Successful:" in out
        assert "8" in out
        assert "Failed:" in out
        assert "Rebases:" in out
        assert "83%" in out  # 10/12
        assert "Max queue depth:" in out
        assert "3" in out

    def test_skips_high_conflict_when_zero(self, capsys):
        mqs = MergeQueueStats(total_merges=1, successful_merges=1,
                              merge_durations=[1.0], wait_times=[0.1],
                              queue_depth_samples=[1],
                              total_rebases=1, successful_rebases=1)
        _print_merge_queue_stats(mqs)
        out = capsys.readouterr().out
        assert "High-conflict" not in out

    def test_shows_high_conflict_section(self, capsys):
        mqs = MergeQueueStats(
            total_merges=2, successful_merges=2,
            total_rebases=3, successful_rebases=3,
            high_conflict_merges=1,
            double_rebase_overhead_seconds=[2.5],
            merge_durations=[1.0, 2.0], wait_times=[0.1, 0.2],
            queue_depth_samples=[1],
        )
        _print_merge_queue_stats(mqs)
        out = capsys.readouterr().out
        assert "High-conflict" in out
        assert "Double-rebase" in out


class TestSerializeMergeQueueStats:
    """serialize_session_stats includes merge_queue when present."""

    def test_no_merge_queue_key_when_empty(self):
        ss = SessionStats(agent_stats=AgentStats())
        data = serialize_session_stats(ss, 100.0, 2, 5)
        assert "merge_queue" not in data

    def test_merge_queue_key_present_when_populated(self):
        ss = SessionStats(agent_stats=AgentStats())
        ss.merge_queue_stats = MergeQueueStats(
            total_merges=3, successful_merges=2, failed_merges=1,
            merge_durations=[1.0, 2.0, 3.0], wait_times=[0.1, 0.2, 0.3],
            queue_depth_samples=[1, 2, 3],
            total_rebases=4, successful_rebases=3, failed_rebases=1,
        )
        data = serialize_session_stats(ss, 100.0, 2, 5)
        assert "merge_queue" in data
        mq = data["merge_queue"]
        assert mq["total_merges"] == 3
        assert mq["successful_merges"] == 2
        assert mq["avg_merge_duration_s"] == 2.0
        assert mq["rebase_success_rate"] == 0.75


# Need pytest import for approx
import pytest
