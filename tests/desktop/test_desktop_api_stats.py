"""Tests for desktop_api_stats serialization helpers."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from pokepoke.desktop.desktop_api_stats import (
    _compute_idle_ratio,
    get_cached_leaderboard,
    get_lock_contention_stats,
    get_merge_queue_stats,
    get_model_history,
    get_model_leaderboard,
    get_operation_timings,
    get_performance_metrics,
    get_repo_summary,
    push_stats,
    serialize_live_stats,
    snapshot_to_dict,
)
from pokepoke.types import (
    AgentStats,
    BeadsCreatedItem,
    BeadsWorkItem,
    ModelCompletionRecord,
    SessionStats,
)


def _make_stats(**kwargs) -> SessionStats:
    """Create a SessionStats with defaults for testing."""
    return SessionStats(agent_stats=AgentStats(), **kwargs)


def _make_self(**kwargs):
    """Create a minimal 'self' mock for mixin functions."""
    defaults = {
        "_live_session_stats": None,
        "_current_stats": None,
        "_session_start_time": None,
        "_session_end_time": None,
        "_leaderboard_cache_time": 0.0,
        "_leaderboard_cache": {},
        "_history_cache": None,
        "_history_cache_limit": None,
        "_history_cache_time": 0.0,
        "_lock": threading.RLock(),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestSnapshotToDict:
    """Tests for snapshot_to_dict."""

    def test_returns_all_required_keys(self) -> None:
        stats = _make_stats()
        d = snapshot_to_dict(stats.snapshot())
        expected_keys = {
            "agent_stats",
            "items_completed",
            "items_created",
            "net_items_delta",
            "lifetime_items_created",
            "lifetime_items_completed",
            "created_counts_by_agent_type",
            "completed_counts_by_agent_type",
            "completed_items",
            "created_items",
            "work_agent_runs",
            "gate_agent_runs",
            "tech_debt_agent_runs",
            "janitor_agent_runs",
            "backlog_cleanup_agent_runs",
            "cleanup_agent_runs",
            "beta_tester_agent_runs",
            "code_review_agent_runs",
            "worktree_cleanup_agent_runs",
            "agent_type_elapsed_seconds",
            "model_completions",
            "merge_queue_stats",
        }
        assert expected_keys.issubset(d.keys())

    def test_agent_type_elapsed_seconds_empty_by_default(self) -> None:
        stats = _make_stats()
        d = snapshot_to_dict(stats.snapshot())
        assert d["agent_type_elapsed_seconds"] == {}

    def test_agent_type_elapsed_seconds_recorded(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", 120.0)
        stats.record_agent_elapsed_time("gate", 45.5)
        d = snapshot_to_dict(stats.snapshot())
        assert d["agent_type_elapsed_seconds"]["work"] == 120.0
        assert d["agent_type_elapsed_seconds"]["gate"] == 45.5

    def test_agent_type_elapsed_seconds_accumulates(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", 60.0)
        stats.record_agent_elapsed_time("work", 40.0)
        d = snapshot_to_dict(stats.snapshot())
        assert d["agent_type_elapsed_seconds"]["work"] == 100.0

    def test_net_items_delta(self) -> None:
        stats = _make_stats()
        stats.items_created = 5
        item = BeadsWorkItem(id="x-1", title="t", status="done", priority=1, issue_type="task")
        stats.record_completion(item)
        stats.record_completion(item.__class__(id="x-2", title="t2", status="done", priority=1, issue_type="task"))
        d = snapshot_to_dict(stats.snapshot())
        assert d["items_created"] == 5
        assert d["items_completed"] == 2
        assert d["net_items_delta"] == 3

    def test_agent_runs_serialized(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("work")
        stats.record_agent_run("gate", 2)
        d = snapshot_to_dict(stats.snapshot())
        assert d["work_agent_runs"] == 1
        assert d["gate_agent_runs"] == 2

    def test_model_completions_serialized(self) -> None:
        stats = _make_stats()
        mc = ModelCompletionRecord(item_id="i-1", model="gpt-4", duration_seconds=30.0, gate_passed=True)
        stats.record_model_completion(mc)
        d = snapshot_to_dict(stats.snapshot())
        assert len(d["model_completions"]) == 1
        assert d["model_completions"][0]["item_id"] == "i-1"

    def test_completed_items_list(self) -> None:
        stats = _make_stats()
        item = BeadsWorkItem(id="p-1", title="Do thing", status="done", priority=1, issue_type="task")
        stats.record_completion(item)
        d = snapshot_to_dict(stats.snapshot())
        assert len(d["completed_items"]) == 1
        assert d["completed_items"][0]["id"] == "p-1"

    def test_created_items_list(self) -> None:
        stats = _make_stats()
        ci = BeadsCreatedItem(id="c-1", title="New item", agent_type="work")
        stats.record_created_item(ci)
        d = snapshot_to_dict(stats.snapshot())
        assert len(d["created_items"]) == 1
        assert d["created_items"][0]["id"] == "c-1"

    def test_elapsed_seconds_is_a_plain_dict(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("janitor", 10.0)
        d = snapshot_to_dict(stats.snapshot())
        # Must be JSON-serialisable plain dict
        assert isinstance(d["agent_type_elapsed_seconds"], dict)


class TestSerializeLiveStats:
    def test_returns_none_with_no_data(self) -> None:
        obj = _make_self()
        assert serialize_live_stats(obj) is None

    def test_returns_dict_from_live_session_stats(self) -> None:
        stats = _make_stats()
        obj = _make_self(_live_session_stats=stats)
        result = serialize_live_stats(obj)
        assert result is not None
        assert "agent_stats" in result

    def test_copies_elapsed_time_from_current_stats(self) -> None:
        stats = _make_stats()
        obj = _make_self(
            _live_session_stats=stats,
            _current_stats={"elapsed_time": 99.0},
        )
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["elapsed_time"] == 99.0

    def test_falls_back_to_current_stats_when_no_live(self) -> None:
        obj = _make_self(_current_stats={"elapsed_time": 42.0, "foo": "bar"})
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["foo"] == "bar"

    def test_live_elapsed_time_from_session_start(self) -> None:
        obj = _make_self(_session_start_time=time.time() - 10.0)
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["elapsed_time"] >= 9.0

    def test_live_elapsed_time_overrides_when_stats_present(self) -> None:
        """Elapsed time from session start overrides any existing elapsed_time in stats."""
        stats = _make_stats()
        t0 = time.time() - 20.0
        obj = _make_self(
            _live_session_stats=stats,
            _current_stats={"elapsed_time": 999.0},
            _session_start_time=t0,
        )
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["elapsed_time"] >= 19.0

    def test_live_elapsed_time_uses_session_end_when_set(self) -> None:
        t0 = time.time() - 100.0
        obj = _make_self(_session_start_time=t0, _session_end_time=t0 + 50.0)
        result = serialize_live_stats(obj)
        assert result is not None
        assert abs(result["elapsed_time"] - 50.0) < 1.0


class TestGetCachedLeaderboard:
    def test_returns_cached_value_within_ttl(self) -> None:
        cached = {"model-a": {"success_rate": 0.9}}
        obj = _make_self(_leaderboard_cache=cached, _leaderboard_cache_time=time.time())
        result = get_cached_leaderboard(obj)
        assert result is cached

    def test_refreshes_stale_cache(self) -> None:
        fresh = {"model-b": {"success_rate": 0.8}}
        obj = _make_self(_leaderboard_cache={}, _leaderboard_cache_time=0.0)
        with patch("pokepoke.models.model_stats_store.get_model_summary", return_value=fresh):
            result = get_cached_leaderboard(obj)
        assert result == fresh


class TestGetModelLeaderboard:
    def test_calls_get_model_summary(self) -> None:
        obj = _make_self()
        expected = {"model-x": {"total_items_attempted": 5}}
        with patch("pokepoke.models.model_stats_store.get_model_summary", return_value=expected):
            result = get_model_leaderboard(obj)
        assert result == expected


class TestGetModelHistory:
    def test_returns_empty_for_non_positive_limit(self) -> None:
        obj = _make_self()
        assert get_model_history(obj, limit=0) == []
        assert get_model_history(obj, limit=-1) == []

    def test_returns_cached_history(self) -> None:
        # Cached data should already be normalized
        cached = [{"item_id": "x", "duration_seconds": 45.0, "gate_passed": False}]
        obj = _make_self(
            _history_cache=cached,
            _history_cache_limit=200,
            _history_cache_time=time.time(),
        )
        result = get_model_history(obj)
        assert result == cached

    def test_fetches_and_stores_new_history(self) -> None:
        obj = _make_self()
        # Mock raw data from backend (before normalization)
        raw_data = [{"work_item_id": "new", "wall_time_seconds": 30.0, "quality_gates_passed": True}]
        # Expected normalized data
        normalized = [{"item_id": "new", "duration_seconds": 30.0, "gate_passed": True}]

        with patch("pokepoke.models.model_history.load_model_history_entries", return_value=raw_data):
            result = get_model_history(obj, limit=10)

        assert result == normalized
        assert obj._history_cache == normalized
        assert obj._history_cache_limit == 10

    def test_normalizes_model_history_keys(self) -> None:
        """Test that backend keys are mapped to frontend schema."""
        obj = _make_self()
        # Raw data with backend keys
        raw_data = [
            {
                "timestamp": "2024-01-01T00:00:00",
                "model": "gpt-4",
                "work_item_id": "PokePoke-123",
                "title": "Fix bug",
                "issue_type": "bug",
                "labels": ["backend", "critical"],
                "wall_time_seconds": 45.5,
                "quality_gates_passed": True,
                "success": True,
                "retry_attempts": 0,
            }
        ]

        with patch("pokepoke.models.model_history.load_model_history_entries", return_value=raw_data):
            result = get_model_history(obj, limit=10)

        assert len(result) == 1
        entry = result[0]

        # Check normalized keys exist
        assert entry["item_id"] == "PokePoke-123"
        assert entry["duration_seconds"] == 45.5
        assert entry["gate_passed"] is True

        # Check old keys are removed
        assert "work_item_id" not in entry
        assert "wall_time_seconds" not in entry
        assert "quality_gates_passed" not in entry

        # Check other fields are preserved
        assert entry["timestamp"] == "2024-01-01T00:00:00"
        assert entry["model"] == "gpt-4"
        assert entry["title"] == "Fix bug"
        assert entry["issue_type"] == "bug"
        assert entry["labels"] == ["backend", "critical"]
        assert entry["success"] is True
        assert entry["retry_attempts"] == 0


class TestPushStats:
    def test_stores_live_session_stats(self) -> None:
        stats = _make_stats()
        obj = _make_self()
        push_stats(obj, stats)
        assert obj._live_session_stats is stats

    def test_stores_current_stats_with_elapsed_time(self) -> None:
        stats = _make_stats()
        obj = _make_self()
        push_stats(obj, stats, elapsed_time=77.5)
        assert obj._current_stats["elapsed_time"] == 77.5

    def test_handles_none_session_stats(self) -> None:
        obj = _make_self()
        push_stats(obj, None, elapsed_time=5.0)
        assert obj._current_stats["elapsed_time"] == 5.0
        assert obj._live_session_stats is None


# ── Repo-filtered leaderboard and history ────────────────────────────


class TestGetModelLeaderboardByRepo:
    def test_no_repo_calls_global_summary(self) -> None:
        obj = _make_self()
        expected = {"model-x": {"total_items_attempted": 5}}
        with patch("pokepoke.models.model_stats_store.get_model_summary", return_value=expected):
            result = get_model_leaderboard(obj)
        assert result == expected

    def test_with_repo_calls_summary_by_repo(self) -> None:
        obj = _make_self()
        expected = {"model-y": {"total_items_attempted": 3}}
        with patch("pokepoke.models.model_stats_store.get_model_summary_by_repo", return_value=expected) as mock_fn:
            result = get_model_leaderboard(obj, repo_name="RepoA")
        assert result == expected
        mock_fn.assert_called_once_with(repo_name="RepoA")


class TestGetModelHistoryByRepo:
    def test_repo_filter_passed_to_loader(self) -> None:
        """repo_name must be forwarded to load_model_history_entries."""
        obj = _make_self()
        filtered_data = [
            {"item_id": "A1", "repo_name": "RepoA", "duration_seconds": 10},
        ]
        with patch(
            "pokepoke.models.model_history.load_model_history_entries",
            return_value=filtered_data,
        ) as mock_load:
            result = get_model_history(obj, limit=10, repo_name="RepoA")
        mock_load.assert_called_once_with(limit=10, repo_name="RepoA")
        assert len(result) == 1
        assert result[0]["item_id"] == "A1"

    def test_repo_filter_skips_cache(self) -> None:
        """Filtering by repo should bypass the history cache."""
        cached = [{"item_id": "cached", "repo_name": ""}]
        obj = _make_self(
            _history_cache=cached,
            _history_cache_limit=200,
            _history_cache_time=time.time(),
        )
        raw_data = [{"item_id": "X1", "repo_name": "RepoX"}]
        with patch("pokepoke.models.model_history.load_model_history_entries", return_value=raw_data):
            result = get_model_history(obj, limit=200, repo_name="RepoX")
        assert len(result) == 1
        assert result[0]["item_id"] == "X1"


class TestGetRepoSummary:
    def test_combines_model_and_beads_metrics(self) -> None:
        obj = _make_self()
        model_metrics = {
            "RepoA": {
                "total_items_processed": 10,
                "total_succeeded": 8,
                "total_failed": 2,
                "success_rate": 0.8,
                "total_cost": 1.50,
            },
        }
        beads_metrics = {
            "RepoA": {
                "total_created": 5,
                "total_completed": 3,
                "net_delta": 2,
            },
        }
        with patch("pokepoke.models.model_stats_store.get_repo_summary_metrics", return_value=model_metrics), \
             patch("pokepoke.beads.beads_item_stats_store.get_summary_by_repo", return_value=beads_metrics):
            result = get_repo_summary(obj)

        assert "RepoA" in result
        assert result["RepoA"]["total_items_processed"] == 10
        assert result["RepoA"]["success_rate"] == 0.8
        assert result["RepoA"]["total_cost"] == 1.50
        assert result["RepoA"]["items_created"] == 5
        assert result["RepoA"]["items_completed"] == 3
        assert result["RepoA"]["net_items_delta"] == 2

    def test_handles_repos_only_in_beads(self) -> None:
        obj = _make_self()
        beads_metrics = {
            "RepoB": {"total_created": 2, "total_completed": 0, "net_delta": 2},
        }
        with patch("pokepoke.models.model_stats_store.get_repo_summary_metrics", return_value={}), \
             patch("pokepoke.beads.beads_item_stats_store.get_summary_by_repo", return_value=beads_metrics):
            result = get_repo_summary(obj)

        assert "RepoB" in result
        assert result["RepoB"]["total_items_processed"] == 0
        assert result["RepoB"]["items_created"] == 2

    def test_empty_returns_empty(self) -> None:
        obj = _make_self()
        with patch("pokepoke.models.model_stats_store.get_repo_summary_metrics", return_value={}), \
             patch("pokepoke.beads.beads_item_stats_store.get_summary_by_repo", return_value={}):
            result = get_repo_summary(obj)
        assert result == {}


class TestSerializeLiveStatsThreadSafety:
    """Verify serialize_live_stats acquires the lock."""

    def test_reads_under_lock(self) -> None:
        """Concurrent writes to fields should not cause torn reads."""
        obj = _make_self(_session_start_time=time.time() - 5.0)
        results: list[dict[str, Any] | None] = []
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(50):
                    results.append(serialize_live_stats(obj))
            except Exception as e:
                errors.append(e)

        def writer() -> None:
            for i in range(50):
                with obj._lock:
                    obj._session_start_time = time.time() - float(i)

        threads = [threading.Thread(target=reader), threading.Thread(target=writer)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors
        # All results should be either None or a dict with elapsed_time
        for r in results:
            if r is not None:
                assert "elapsed_time" in r


class TestGetCachedLeaderboardThreadSafety:
    """Verify get_cached_leaderboard acquires the lock."""

    def test_concurrent_access_no_race(self) -> None:
        """Multiple threads calling get_cached_leaderboard should not corrupt cache."""
        fresh = {"model": {"rate": 0.9}}
        obj = _make_self(_leaderboard_cache={}, _leaderboard_cache_time=0.0)
        errors: list[Exception] = []

        def reader() -> None:
            try:
                for _ in range(30):
                    with patch("pokepoke.models.model_stats_store.get_model_summary", return_value=fresh):
                        result = get_cached_leaderboard(obj)
                    assert isinstance(result, dict)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors


# ── Merge queue stats in snapshot ────────────────────────────────────


class TestSnapshotMergeQueueStats:
    """Tests for merge_queue_stats in snapshot_to_dict."""

    def test_merge_queue_stats_present_in_snapshot(self) -> None:
        stats = _make_stats()
        d = snapshot_to_dict(stats.snapshot())
        assert "merge_queue_stats" in d
        assert isinstance(d["merge_queue_stats"], dict)

    def test_merge_queue_stats_default_values(self) -> None:
        stats = _make_stats()
        d = snapshot_to_dict(stats.snapshot())
        mq = d["merge_queue_stats"]
        assert mq["total_merges"] == 0
        assert mq["successful_merges"] == 0
        assert mq["avg_merge_duration_s"] == 0.0

    def test_merge_queue_stats_with_data(self) -> None:
        from pokepoke.git.merge_queue_stats import MergeQueueStats
        mqs = MergeQueueStats(
            total_merges=10,
            successful_merges=8,
            failed_merges=2,
            merge_durations=[1.0, 2.0, 3.0],
        )
        stats = _make_stats()
        stats.record_merge_queue_stats(mqs)
        d = snapshot_to_dict(stats.snapshot())
        mq = d["merge_queue_stats"]
        assert mq["total_merges"] == 10
        assert mq["successful_merges"] == 8
        assert mq["failed_merges"] == 2
        assert mq["avg_merge_duration_s"] == 2.0


# ── Lock contention stats ────────────────────────────────────────────


class TestGetLockContentionStats:
    def test_returns_dict(self) -> None:
        obj = _make_self()
        mock_data = {"merge-queue": {"acquired": 5, "timeouts": 0}}
        with patch("pokepoke.worktrees.lock_contention.get_lock_contention_stats", return_value=mock_data):
            result = get_lock_contention_stats(obj)
        assert result == mock_data

    def test_returns_empty_when_no_contention(self) -> None:
        obj = _make_self()
        with patch("pokepoke.worktrees.lock_contention.get_lock_contention_stats", return_value={}):
            result = get_lock_contention_stats(obj)
        assert result == {}


# ── Merge queue stats endpoint ───────────────────────────────────────


class TestGetMergeQueueStats:
    def test_returns_queue_summary_with_live_depth(self) -> None:
        obj = _make_self()
        mock_mq = SimpleNamespace(
            stats=SimpleNamespace(to_summary_dict=lambda: {
                "total_merges": 5, "successful_merges": 4, "failed_merges": 1,
            }),
            pending_count=2,
            is_running=True,
        )
        with patch("pokepoke.git.merge_queue.get_merge_queue", return_value=mock_mq):
            result = get_merge_queue_stats(obj)
        assert result["total_merges"] == 5
        assert result["current_queue_depth"] == 2
        assert result["is_running"] is True

    def test_returns_empty_on_exception(self) -> None:
        obj = _make_self()
        with patch("pokepoke.git.merge_queue.get_merge_queue", side_effect=RuntimeError("not started")):
            result = get_merge_queue_stats(obj)
        assert result == {}


# ── Operation timings endpoint ───────────────────────────────────────


class TestGetOperationTimings:
    def test_returns_timing_summary(self) -> None:
        obj = _make_self()
        mock_summary = {
            "worktree.create": {"count": 3, "mean": 1.5, "p50": 1.2, "p95": 2.0, "p99": 2.1,
                                "min": 0.8, "max": 2.5, "total": 4.5},
        }
        with patch("pokepoke.stats.perf_timing.get_registry") as mock_reg:
            mock_reg.return_value.summary.return_value = mock_summary
            result = get_operation_timings(obj)
        assert "worktree.create" in result
        assert result["worktree.create"]["count"] == 3

    def test_returns_empty_when_no_timings(self) -> None:
        obj = _make_self()
        with patch("pokepoke.stats.perf_timing.get_registry") as mock_reg:
            mock_reg.return_value.summary.return_value = {}
            result = get_operation_timings(obj)
        assert result == {}


# ── Idle/productive ratio ────────────────────────────────────────────


class TestComputeIdleRatio:
    def test_no_session_start_returns_zeros(self) -> None:
        obj = _make_self(_session_start_time=None)
        result = _compute_idle_ratio(obj)
        assert result["total_seconds"] == 0.0
        assert result["idle_ratio"] == 0.0

    def test_all_idle_when_no_stats(self) -> None:
        obj = _make_self(
            _session_start_time=time.time() - 100.0,
            _session_end_time=None,
            _live_session_stats=None,
        )
        result = _compute_idle_ratio(obj)
        assert result["total_seconds"] >= 99.0
        assert result["productive_seconds"] == 0.0
        assert result["idle_ratio"] >= 0.99

    def test_with_productive_time(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", 40.0)
        stats.record_agent_elapsed_time("gate", 10.0)
        t0 = time.time() - 100.0
        obj = _make_self(
            _session_start_time=t0,
            _session_end_time=t0 + 100.0,
            _live_session_stats=stats,
        )
        result = _compute_idle_ratio(obj)
        assert result["total_seconds"] == 100.0
        assert result["productive_seconds"] == 50.0
        assert result["idle_seconds"] == 50.0
        assert abs(result["idle_ratio"] - 0.5) < 0.01

    def test_uses_session_end_time(self) -> None:
        t0 = time.time() - 200.0
        obj = _make_self(
            _session_start_time=t0,
            _session_end_time=t0 + 60.0,
            _live_session_stats=None,
        )
        result = _compute_idle_ratio(obj)
        assert abs(result["total_seconds"] - 60.0) < 1.0


# ── Combined performance metrics ─────────────────────────────────────


class TestGetPerformanceMetrics:
    def test_returns_all_sections(self) -> None:
        obj = _make_self(
            _session_start_time=time.time() - 10.0,
            _session_end_time=None,
            _live_session_stats=None,
        )
        mock_mq = SimpleNamespace(
            stats=SimpleNamespace(to_summary_dict=lambda: {"total_merges": 1}),
            pending_count=0,
            is_running=False,
        )
        mock_monitor = SimpleNamespace(snapshot=lambda: {
            "enabled": True, "total_checks": 5, "total_alerts": 1,
        })
        with patch("pokepoke.git.merge_queue.get_merge_queue", return_value=mock_mq), \
             patch("pokepoke.worktrees.lock_contention.get_lock_contention_stats", return_value={"lock-a": {}}), \
             patch("pokepoke.stats.perf_timing.get_registry") as mock_reg, \
             patch("pokepoke.stats.performance_monitor.get_performance_monitor", return_value=mock_monitor):
            mock_reg.return_value.summary.return_value = {"op.x": {"count": 2}}
            result = get_performance_metrics(obj)

        assert "merge_queue" in result
        assert result["merge_queue"]["total_merges"] == 1
        assert "lock_contention" in result
        assert "lock-a" in result["lock_contention"]
        assert "operation_timings" in result
        assert "op.x" in result["operation_timings"]
        assert "performance_monitor" in result
        assert result["performance_monitor"]["enabled"] is True
        assert "idle_productive_ratio" in result
        assert result["idle_productive_ratio"]["total_seconds"] >= 9.0

    def test_merge_queue_failure_returns_empty_section(self) -> None:
        obj = _make_self(
            _session_start_time=None,
            _session_end_time=None,
            _live_session_stats=None,
        )
        mock_monitor = SimpleNamespace(snapshot=lambda: {"enabled": False})
        with patch("pokepoke.git.merge_queue.get_merge_queue", side_effect=RuntimeError), \
             patch("pokepoke.worktrees.lock_contention.get_lock_contention_stats", return_value={}), \
             patch("pokepoke.stats.perf_timing.get_registry") as mock_reg, \
             patch("pokepoke.stats.performance_monitor.get_performance_monitor", return_value=mock_monitor):
            mock_reg.return_value.summary.return_value = {}
            result = get_performance_metrics(obj)

        assert result["merge_queue"] == {}
        assert result["idle_productive_ratio"]["total_seconds"] == 0.0
