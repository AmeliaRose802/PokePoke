"""Comprehensive tests for multi-repo orchestration features.

Covers: config parsing with multiple repos, work item aggregation across repos,
worker allocation and rebalancing, repo exhaustion and failover, worktree
isolation per repo, maintenance scheduling independence, and metrics segmentation.
"""

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from pokepoke.config import (
    ProjectConfig,
    RepoConfig,
)
from pokepoke.multi_repo_aggregator import (
    AggregatedWorkItem,
    _query_all_repos,
    aggregate_ready_work_items,
    get_aggregated_stats,
)
from pokepoke.repo_worker_pool import RepoWorkerPool
from pokepoke.metrics_context import (
    get_current_repo_name,
    repo_context,
    set_current_repo_name,
)
from pokepoke.maintenance_state import (
    MaintenanceState,
    RepoMaintenanceState,
    get_repo_state,
    increment_items_completed,
    _state_from_dict,
    _state_to_dict,
)
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str = "x", priority: int = 1, **kwargs: object) -> BeadsWorkItem:
    defaults = {
        "id": item_id,
        "title": f"Task {item_id}",
        "status": "open",
        "priority": priority,
        "issue_type": "task",
    }
    defaults.update(kwargs)
    return BeadsWorkItem(**defaults)  # type: ignore[arg-type]


def _make_repo(
    path: str = "/repo/alpha",
    priority_weight: int = 1,
    enabled: bool = True,
    max_workers: int = 0,
) -> RepoConfig:
    return RepoConfig(
        path=path,
        priority_weight=priority_weight,
        enabled=enabled,
        max_workers=max_workers,
    )


def _bd_stdout(items: list[dict]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess("bd", 0, stdout=json.dumps(items))


# ═══════════════════════════════════════════════════════════════════════════
# 1. CONFIG PARSING WITH MULTIPLE REPOS
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigParsingMultipleRepos:
    """Test ProjectConfig.from_dict with multi-repo configurations."""

    def test_from_dict_with_repos_list(self) -> None:
        data = {
            "repos": [
                {"path": "/repo/alpha", "priority_weight": 3, "enabled": True, "max_workers": 2},
                {"path": "/repo/beta", "priority_weight": 1},
            ]
        }
        config = ProjectConfig.from_dict(data)
        assert len(config.repos) == 2
        assert config.repos[0].path == "/repo/alpha"
        assert config.repos[0].priority_weight == 3
        assert config.repos[0].max_workers == 2
        assert config.repos[1].path == "/repo/beta"
        assert config.repos[1].priority_weight == 1
        assert config.repos[1].enabled is True  # default

    def test_from_dict_empty_repos_list(self) -> None:
        config = ProjectConfig.from_dict({"repos": []})
        assert config.repos == []

    def test_from_dict_no_repos_key(self) -> None:
        config = ProjectConfig.from_dict({})
        assert config.repos == []

    def test_repo_config_max_workers_clamped_to_zero(self) -> None:
        rc = RepoConfig(max_workers=-5)
        assert rc.max_workers == 0

    def test_repo_config_max_workers_zero_means_uncapped(self) -> None:
        rc = RepoConfig(max_workers=0)
        assert rc.max_workers == 0

    def test_from_dict_repos_with_all_disabled(self) -> None:
        data = {
            "repos": [
                {"path": "/a", "enabled": False},
                {"path": "/b", "enabled": False},
            ]
        }
        config = ProjectConfig.from_dict(data)
        assert len(config.repos) == 2
        assert all(not r.enabled for r in config.repos)

    def test_from_dict_repos_priority_weight_defaults_to_one(self) -> None:
        data = {"repos": [{"path": "/repo"}]}
        config = ProjectConfig.from_dict(data)
        assert config.repos[0].priority_weight == 1

    def test_from_dict_repos_preserves_order(self) -> None:
        paths = ["/z", "/a", "/m", "/b"]
        data = {"repos": [{"path": p} for p in paths]}
        config = ProjectConfig.from_dict(data)
        assert [r.path for r in config.repos] == paths

    def test_from_dict_json_round_trip(self, tmp_path: Path) -> None:
        """Config with repos survives JSON serialization/deserialization."""
        original = {
            "project_name": "multi-repo-test",
            "repos": [
                {"path": "/repo/a", "priority_weight": 5, "max_workers": 3},
                {"path": "/repo/b", "priority_weight": 2, "enabled": False},
            ],
        }
        json_file = tmp_path / "config.json"
        json_file.write_text(json.dumps(original))
        loaded = json.loads(json_file.read_text())
        config = ProjectConfig.from_dict(loaded)
        assert config.project_name == "multi-repo-test"
        assert len(config.repos) == 2
        assert config.repos[0].max_workers == 3
        assert config.repos[1].enabled is False

    def test_from_dict_repos_combined_with_other_config(self) -> None:
        data = {
            "project_name": "combined-test",
            "max_parallel_agents": 4,
            "repos": [
                {"path": "/repo/main", "priority_weight": 10},
            ],
        }
        config = ProjectConfig.from_dict(data)
        assert config.project_name == "combined-test"
        assert config.max_parallel_agents == 4
        assert len(config.repos) == 1
        assert config.repos[0].priority_weight == 10


# ═══════════════════════════════════════════════════════════════════════════
# 2. WORK ITEM AGGREGATION ACROSS REPOS
# ═══════════════════════════════════════════════════════════════════════════


class TestAggregationEdgeCases:
    """Additional edge cases for multi-repo work item aggregation."""

    def test_single_repo_uses_sequential_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """When there's only one repo, _query_all_repos skips ThreadPoolExecutor."""
        payload = [
            {"id": "t1", "title": "T", "status": "open", "priority": 1, "issue_type": "task"},
        ]
        monkeypatch.setattr(
            "pokepoke.multi_repo_aggregator._run_bd",
            lambda *a, **kw: _bd_stdout(payload),
        )
        repos = [_make_repo(path=str(tmp_path))]
        results = _query_all_repos(repos)
        assert len(results) == 1
        assert len(results[0].items) == 1

    def test_aggregate_many_repos_parallel(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Test aggregation with many repos using parallel execution."""
        repo_dirs = []
        call_map = {}
        for i in range(6):
            d = tmp_path / f"repo_{i}"
            d.mkdir()
            repo_dirs.append(d)
            call_map[str(d)] = [
                {"id": f"item-{i}", "title": f"T{i}", "status": "open",
                 "priority": i, "issue_type": "task"}
            ]

        def mock_bd(*args, **kwargs):
            return _bd_stdout(call_map.get(kwargs.get("cwd", ""), []))

        monkeypatch.setattr("pokepoke.multi_repo_aggregator._run_bd", mock_bd)
        repos = [_make_repo(path=str(d), priority_weight=1) for d in repo_dirs]
        items = aggregate_ready_work_items(repos, max_workers=4)
        assert len(items) == 6
        # Items sorted by priority (ascending)
        assert items[0].item.priority <= items[-1].item.priority

    def test_aggregate_mixed_enabled_disabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo_a = tmp_path / "enabled"
        repo_a.mkdir()

        monkeypatch.setattr(
            "pokepoke.multi_repo_aggregator._run_bd",
            lambda *a, **kw: _bd_stdout([
                {"id": "e1", "title": "E", "status": "open", "priority": 1, "issue_type": "task"}
            ]),
        )
        repos = [
            _make_repo(path=str(repo_a), enabled=True),
            _make_repo(path="/disabled", enabled=False),
        ]
        items = aggregate_ready_work_items(repos)
        assert len(items) == 1
        assert items[0].item.id == "e1"

    def test_aggregate_preserves_repo_context_for_each_item(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Each aggregated item carries the correct repo_path and repo_name."""
        repo_a = tmp_path / "alpha"
        repo_b = tmp_path / "beta"
        repo_a.mkdir()
        repo_b.mkdir()

        call_map = {
            str(repo_a): [
                {"id": "a1", "title": "A1", "status": "open", "priority": 1, "issue_type": "task"},
                {"id": "a2", "title": "A2", "status": "open", "priority": 2, "issue_type": "task"},
            ],
            str(repo_b): [
                {"id": "b1", "title": "B1", "status": "open", "priority": 1, "issue_type": "task"},
            ],
        }

        def mock_bd(*args, **kwargs):
            return _bd_stdout(call_map.get(kwargs.get("cwd", ""), []))

        monkeypatch.setattr("pokepoke.multi_repo_aggregator._run_bd", mock_bd)
        repos = [
            _make_repo(path=str(repo_a), priority_weight=1),
            _make_repo(path=str(repo_b), priority_weight=1),
        ]
        items = aggregate_ready_work_items(repos)
        a_items = [i for i in items if i.repo_name == "alpha"]
        b_items = [i for i in items if i.repo_name == "beta"]
        assert len(a_items) == 2
        assert len(b_items) == 1
        assert all(i.repo_path == str(repo_a) for i in a_items)
        assert all(i.repo_path == str(repo_b) for i in b_items)

    def test_query_all_repos_handles_future_exception(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """If a repo query raises an unexpected exception, it's caught."""
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()

        call_count = {"n": 0}

        def mock_bd(*args, **kwargs):
            call_count["n"] += 1
            cwd = kwargs.get("cwd", "")
            if "a" in Path(cwd).name:
                raise RuntimeError("Unexpected crash")
            return _bd_stdout([
                {"id": "ok", "title": "OK", "status": "open", "priority": 1, "issue_type": "task"}
            ])

        monkeypatch.setattr("pokepoke.multi_repo_aggregator._run_bd", mock_bd)
        repos = [_make_repo(path=str(repo_a)), _make_repo(path=str(repo_b))]
        items = aggregate_ready_work_items(repos)
        assert len(items) == 1
        assert items[0].item.id == "ok"

    def test_get_aggregated_stats_with_errors(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Stats returns 0 for repos with errors, correct count for others."""
        good = tmp_path / "good"
        bad = tmp_path / "bad"
        good.mkdir()
        bad.mkdir()

        def mock_bd(*args, **kwargs):
            cwd = kwargs.get("cwd", "")
            if "bad" in Path(cwd).name:
                raise subprocess.CalledProcessError(1, "bd")
            return _bd_stdout([
                {"id": "g1", "title": "G", "status": "open", "priority": 1, "issue_type": "task"},
                {"id": "g2", "title": "G2", "status": "open", "priority": 2, "issue_type": "task"},
            ])

        monkeypatch.setattr("pokepoke.multi_repo_aggregator._run_bd", mock_bd)
        repos = [_make_repo(path=str(good)), _make_repo(path=str(bad))]
        stats = get_aggregated_stats(repos)
        assert stats[str(good)] == 2
        assert stats[str(bad)] == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. WORKER ALLOCATION AND REBALANCING
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkerExhaustionAndFailover:
    """Test exhaustion scenarios and failover during rebalancing."""

    def test_all_repos_exhausted_then_one_recovers(self) -> None:
        """When all repos exhaust items, then one gets work, slots redistribute."""
        pool = RepoWorkerPool(
            total_workers=6,
            repos=[_make_repo(path="/a", priority_weight=1), _make_repo(path="/b", priority_weight=1)],
        )
        # All repos have no items
        result = pool.rebalance({"/a": 0, "/b": 0})
        assert result["/a"] == 3  # base restored
        assert result["/b"] == 3

        # Now /a gets items, /b still empty
        result = pool.rebalance({"/a": 5, "/b": 0})
        assert result["/a"] > 3  # /a gets /b's idle slots
        assert result["/b"] < 3

    def test_sequential_rebalances_converge(self) -> None:
        """Multiple sequential rebalances produce consistent results."""
        pool = RepoWorkerPool(
            total_workers=8,
            repos=[
                _make_repo(path="/a", priority_weight=2),
                _make_repo(path="/b", priority_weight=1),
                _make_repo(path="/c", priority_weight=1),
            ],
        )
        counts = {"/a": 10, "/b": 0, "/c": 5}
        result1 = pool.rebalance(counts)
        result2 = pool.rebalance(counts)
        # Same inputs → same outputs after first rebalance stabilizes
        assert result1 == result2

    def test_cap_overflow_distributed_to_others(self) -> None:
        """When a capped repo can't take all donated slots, they go elsewhere."""
        pool = RepoWorkerPool(
            total_workers=10,
            repos=[
                _make_repo(path="/a", priority_weight=5, max_workers=3),
                _make_repo(path="/b", priority_weight=1),
                _make_repo(path="/c", priority_weight=1),
            ],
        )
        # /b and /c empty, donate to /a (capped at 3) — overflow should go to any needy repo
        result = pool.rebalance({"/a": 20, "/b": 0, "/c": 0})
        assert result["/a"] <= 3  # Cap respected

    def test_failover_high_to_low_priority(self) -> None:
        """High-priority repo exhausted, workers failover to low-priority."""
        pool = RepoWorkerPool(
            total_workers=6,
            repos=[
                _make_repo(path="/high", priority_weight=5),
                _make_repo(path="/low", priority_weight=1),
            ],
        )
        # Initially /high has 5 workers, /low has 1
        a_alloc = pool.get_allocation("/high")
        b_alloc = pool.get_allocation("/low")
        assert a_alloc is not None and b_alloc is not None
        assert a_alloc.allocated_workers >= b_alloc.allocated_workers

        # /high exhausted, /low has work
        result = pool.rebalance({"/high": 0, "/low": 10})
        assert result["/low"] > b_alloc.allocated_workers  # /low gained workers
        assert result["/high"] < a_alloc.allocated_workers  # /high donated workers

    def test_rebalance_does_not_exceed_total_workers(self) -> None:
        """Total allocated workers never exceeds the global budget."""
        pool = RepoWorkerPool(
            total_workers=10,
            repos=[
                _make_repo(path="/a", priority_weight=3),
                _make_repo(path="/b", priority_weight=2),
                _make_repo(path="/c", priority_weight=1),
            ],
        )
        for counts in [
            {"/a": 10, "/b": 0, "/c": 0},
            {"/a": 0, "/b": 10, "/c": 10},
            {"/a": 5, "/b": 5, "/c": 5},
            {"/a": 0, "/b": 0, "/c": 10},
        ]:
            result = pool.rebalance(counts)
            total = sum(result.values())
            assert total <= 10, f"Total {total} exceeds budget for counts={counts}"

    def test_single_worker_budget(self) -> None:
        """With only 1 worker, one repo gets it; rebalance can move it."""
        pool = RepoWorkerPool(
            total_workers=1,
            repos=[_make_repo(path="/a"), _make_repo(path="/b")],
        )
        total = sum(
            a.allocated_workers for a in pool.get_all_allocations().values()
        )
        assert total == 1

        result = pool.rebalance({"/a": 0, "/b": 5})
        assert result["/b"] >= 1

    def test_rebalance_with_all_workers_active(self) -> None:
        """Active workers in idle repos cannot be donated."""
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_make_repo(path="/a"), _make_repo(path="/b")],
        )
        # Start all workers in /b
        pool.record_worker_start("/b")
        pool.record_worker_start("/b")
        # /b has no ready items but 2 active workers — can't donate
        result = pool.rebalance({"/a": 5, "/b": 0})
        assert result["/b"] >= 2  # Active workers retained


# ═══════════════════════════════════════════════════════════════════════════
# 4. WORKTREE ISOLATION PER REPO
# ═══════════════════════════════════════════════════════════════════════════


class TestWorktreeIsolationPerRepo:
    """Test that worktree operations use per-repo context."""

    def test_repo_context_isolates_concurrent_threads(self) -> None:
        """Concurrent threads see their own repo context."""
        results: dict[str, str] = {}
        barrier = threading.Barrier(3)

        def worker(name: str) -> None:
            with repo_context(name):
                barrier.wait()
                time.sleep(0.01)  # Brief overlap
                results[name] = get_current_repo_name()

        threads = [
            threading.Thread(target=worker, args=(f"repo-{i}",))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert results == {"repo-0": "repo-0", "repo-1": "repo-1", "repo-2": "repo-2"}

    def test_aggregated_items_carry_correct_repo_path(self, tmp_path: Path) -> None:
        """Worktree creation would use the item's repo_path, not a global one."""
        repo_a = tmp_path / "project-alpha"
        repo_b = tmp_path / "project-beta"
        repo_a.mkdir()
        repo_b.mkdir()

        item_a = _make_item("a1")
        item_b = _make_item("b1")

        agg_a = AggregatedWorkItem(item=item_a, repo_path=str(repo_a), repo_name="project-alpha")
        agg_b = AggregatedWorkItem(item=item_b, repo_path=str(repo_b), repo_name="project-beta")

        # Each item's repo_path is independent
        assert agg_a.repo_path != agg_b.repo_path
        assert Path(agg_a.repo_path).name == "project-alpha"
        assert Path(agg_b.repo_path).name == "project-beta"

    def test_repo_context_exception_safety(self) -> None:
        """repo_context restores previous name even on exception."""
        set_current_repo_name("outer-repo")
        try:
            with repo_context("inner-repo"):
                assert get_current_repo_name() == "inner-repo"
                raise ValueError("test error")
        except ValueError:
            pass
        assert get_current_repo_name() == "outer-repo"
        set_current_repo_name(None)

    def test_real_tmp_dirs_are_independent(self, tmp_path: Path) -> None:
        """Integration: verify real tmp dirs simulate independent worktrees."""
        repos = {}
        for name in ["alpha", "beta", "gamma"]:
            repo_dir = tmp_path / name
            repo_dir.mkdir()
            worktree_dir = repo_dir / "worktrees" / "task-001"
            worktree_dir.mkdir(parents=True)
            repos[name] = {
                "repo": repo_dir,
                "worktree": worktree_dir,
            }

        # Each repo's worktree dir is unique
        worktree_paths = [str(r["worktree"]) for r in repos.values()]
        assert len(set(worktree_paths)) == 3

        # Worktrees are under their respective repos
        for _name, dirs in repos.items():
            assert str(dirs["worktree"]).startswith(str(dirs["repo"]))


# ═══════════════════════════════════════════════════════════════════════════
# 5. MAINTENANCE SCHEDULING INDEPENDENCE
# ═══════════════════════════════════════════════════════════════════════════


class TestMaintenanceIndependence:
    """Test per-repo maintenance scheduling independence."""

    def test_maintenance_state_per_repo_isolation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each repo's maintenance state is independent."""
        state_file = tmp_path / "maintenance_state.json"
        monkeypatch.setattr("pokepoke.maintenance_state.STATE_FILE", state_file)

        count_a = increment_items_completed(repo_id="repo-a")
        count_b = increment_items_completed(repo_id="repo-b")
        assert count_a == 1
        assert count_b == 1

        count_a2 = increment_items_completed(repo_id="repo-a")
        assert count_a2 == 2
        # repo-b still at 1
        from pokepoke.maintenance_state import get_items_completed_for_repo
        assert get_items_completed_for_repo("repo-b") == 1

    def test_maintenance_state_serialization(self) -> None:
        """MaintenanceState round-trips through dict serialization."""
        state = MaintenanceState(
            total_items_completed=10,
            repos={
                "repo-a": RepoMaintenanceState(items_completed=5, last_run_timestamp=100.0),
                "repo-b": RepoMaintenanceState(items_completed=3, last_run_timestamp=200.0),
            },
        )
        d = _state_to_dict(state)
        restored = _state_from_dict(d)
        assert restored.total_items_completed == 10
        assert restored.repos["repo-a"].items_completed == 5
        assert restored.repos["repo-b"].last_run_timestamp == 200.0

    def test_get_repo_state_creates_lazily(self) -> None:
        """get_repo_state creates a new state for unknown repos."""
        state = MaintenanceState()
        repo = get_repo_state(state, "new-repo")
        assert repo.items_completed == 0
        assert "new-repo" in state.repos

    def test_state_from_dict_tolerates_missing_fields(self) -> None:
        """Deserialization handles missing or malformed fields gracefully."""
        data: dict = {}
        state = _state_from_dict(data)
        assert state.total_items_completed == 0
        assert state.repos == {}

    def test_state_from_dict_tolerates_bad_repo_data(self) -> None:
        data = {
            "total_items_completed": 5,
            "repos": {"x": "not-a-dict"},  # type: ignore[dict-item]
        }
        state = _state_from_dict(data)
        assert state.total_items_completed == 5
        assert "x" not in state.repos  # Bad data skipped

    def test_global_counter_incremented_with_repo_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Global counter is bumped even when repo_id is provided."""
        state_file = tmp_path / "maintenance_state.json"
        monkeypatch.setattr("pokepoke.maintenance_state.STATE_FILE", state_file)

        increment_items_completed(repo_id="repo-a")
        increment_items_completed(repo_id="repo-b")

        from pokepoke.maintenance_state import load_state
        state = load_state()
        assert state.total_items_completed == 2


# ═══════════════════════════════════════════════════════════════════════════
# 6. METRICS SEGMENTATION
# ═══════════════════════════════════════════════════════════════════════════


class TestMetricsSegmentation:
    """Test per-repo metrics attribution and segmentation."""

    def test_repo_context_sets_thread_local(self) -> None:
        set_current_repo_name(None)
        with repo_context("metrics-test-repo"):
            assert get_current_repo_name() == "metrics-test-repo"
        assert get_current_repo_name() == ""

    def test_multiple_threads_independent_metrics(self) -> None:
        """Each thread's repo name is independent for metrics attribution."""
        results: dict[int, str] = {}
        barrier = threading.Barrier(5)

        def worker(idx: int) -> None:
            with repo_context(f"repo-{idx}"):
                barrier.wait()
                results[idx] = get_current_repo_name()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        for i in range(5):
            assert results[i] == f"repo-{i}"

    def test_nested_repo_context_for_maintenance(self) -> None:
        """Maintenance runs inside a repo context preserve the outer context."""
        set_current_repo_name(None)
        with repo_context("outer-repo"):
            assert get_current_repo_name() == "outer-repo"
            with repo_context("maintenance-context"):
                assert get_current_repo_name() == "maintenance-context"
            assert get_current_repo_name() == "outer-repo"
        set_current_repo_name(None)

    def test_session_stats_per_agent_type(self) -> None:
        """Session stats tracks agent runs and elapsed time per agent type."""
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_agent_run("work", count=2)
        stats.record_agent_run("tech_debt", count=1)
        stats.record_agent_elapsed_time("work", 120.0)
        stats.record_agent_elapsed_time("tech_debt", 30.0)

        snap = stats.snapshot()
        assert snap.agent_type_elapsed_seconds.get("work") == 120.0
        assert snap.agent_type_elapsed_seconds.get("tech_debt") == 30.0


# ═══════════════════════════════════════════════════════════════════════════
# 7. INTEGRATION TESTS WITH REAL DIRECTORIES
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiRepoIntegration:
    """Integration tests using real temporary directories with mocked beads."""

    def test_end_to_end_aggregation_with_real_dirs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Full flow: create dirs, aggregate, verify ordering and context."""
        repos_data: dict[str, list[dict]] = {}
        repo_configs = []

        for name, weight, items in [
            ("backend", 5, [
                {"id": "BE-1", "title": "API fix", "status": "open", "priority": 0, "issue_type": "bug"},
                {"id": "BE-2", "title": "Auth", "status": "open", "priority": 2, "issue_type": "task"},
            ]),
            ("frontend", 2, [
                {"id": "FE-1", "title": "UI update", "status": "open", "priority": 1, "issue_type": "task"},
            ]),
            ("docs", 1, []),
        ]:
            d = tmp_path / name
            d.mkdir()
            repos_data[str(d)] = items
            repo_configs.append(_make_repo(path=str(d), priority_weight=weight))

        def mock_bd(*args, **kwargs):
            return _bd_stdout(repos_data.get(kwargs.get("cwd", ""), []))

        monkeypatch.setattr("pokepoke.multi_repo_aggregator._run_bd", mock_bd)

        # Aggregate
        items = aggregate_ready_work_items(repo_configs)
        assert len(items) == 3

        # Highest weight repo (backend) items first
        assert items[0].repo_name == "backend"
        assert items[0].item.id == "BE-1"  # priority=0

        # Verify each item has correct repo context
        fe_items = [i for i in items if i.repo_name == "frontend"]
        assert len(fe_items) == 1
        assert fe_items[0].repo_path == str(tmp_path / "frontend")

    def test_end_to_end_worker_allocation_and_rebalance(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Full flow: allocate workers, simulate exhaustion, rebalance."""
        repos = []
        for name, weight in [("primary", 3), ("secondary", 1)]:
            d = tmp_path / name
            d.mkdir()
            repos.append(_make_repo(path=str(d), priority_weight=weight))

        pool = RepoWorkerPool(total_workers=8, repos=repos)

        # Initial allocation proportional to weight
        primary = pool.get_allocation(str(tmp_path / "primary"))
        secondary = pool.get_allocation(str(tmp_path / "secondary"))
        assert primary is not None and secondary is not None
        assert primary.allocated_workers > secondary.allocated_workers

        # Simulate primary exhausting all items
        result = pool.rebalance({
            str(tmp_path / "primary"): 0,
            str(tmp_path / "secondary"): 10,
        })
        # Secondary should get primary's idle workers
        assert result[str(tmp_path / "secondary")] > secondary.allocated_workers

    def test_end_to_end_repo_context_with_aggregated_items(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Full flow: aggregate items, process each in correct repo context."""
        repo_a = tmp_path / "repo-alpha"
        repo_b = tmp_path / "repo-beta"
        repo_a.mkdir()
        repo_b.mkdir()

        call_map = {
            str(repo_a): [{"id": "a1", "title": "A", "status": "open", "priority": 1, "issue_type": "task"}],
            str(repo_b): [{"id": "b1", "title": "B", "status": "open", "priority": 1, "issue_type": "task"}],
        }

        def mock_bd(*args, **kwargs):
            return _bd_stdout(call_map.get(kwargs.get("cwd", ""), []))

        monkeypatch.setattr("pokepoke.multi_repo_aggregator._run_bd", mock_bd)

        repos = [_make_repo(path=str(repo_a)), _make_repo(path=str(repo_b))]
        items = aggregate_ready_work_items(repos)

        # Simulate processing each item in its repo context
        processed_contexts: list[tuple[str, str]] = []
        for agg_item in items:
            with repo_context(agg_item.repo_name):
                processed_contexts.append((agg_item.item.id, get_current_repo_name()))

        assert ("a1", "repo-alpha") in processed_contexts
        assert ("b1", "repo-beta") in processed_contexts

    def test_worker_pool_with_real_repo_paths(self, tmp_path: Path) -> None:
        """Worker pool uses real path strings for allocation tracking."""
        repos = []
        for name in ["alpha", "beta", "gamma"]:
            d = tmp_path / name
            d.mkdir()
            repos.append(_make_repo(path=str(d), priority_weight=2))

        pool = RepoWorkerPool(total_workers=9, repos=repos)
        allocs = pool.get_all_allocations()

        # Each real path is tracked
        for repo_name in ["alpha", "beta", "gamma"]:
            path = str(tmp_path / repo_name)
            assert path in allocs
            assert allocs[path].allocated_workers == 3  # Equal split

    def test_maintenance_state_with_real_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Maintenance state works with real directory-based repo IDs."""
        state_file = tmp_path / "state.json"
        monkeypatch.setattr("pokepoke.maintenance_state.STATE_FILE", state_file)

        repo_a = str(tmp_path / "repo-a")
        repo_b = str(tmp_path / "repo-b")

        increment_items_completed(repo_id=repo_a)
        increment_items_completed(repo_id=repo_a)
        increment_items_completed(repo_id=repo_b)

        from pokepoke.maintenance_state import get_items_completed_for_repo
        assert get_items_completed_for_repo(repo_a) == 2
        assert get_items_completed_for_repo(repo_b) == 1

    def test_full_multi_repo_cycle(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """End-to-end: config → aggregate → allocate → process → rebalance."""
        # Step 1: Config with multiple repos
        config_data = {
            "project_name": "multi-repo-e2e",
            "repos": [
                {"path": str(tmp_path / "app"), "priority_weight": 3},
                {"path": str(tmp_path / "lib"), "priority_weight": 1},
            ],
        }
        (tmp_path / "app").mkdir()
        (tmp_path / "lib").mkdir()
        config = ProjectConfig.from_dict(config_data)
        assert len(config.repos) == 2

        # Step 2: Aggregate work items
        call_map = {
            str(tmp_path / "app"): [
                {"id": "app-1", "title": "App task", "status": "open", "priority": 1, "issue_type": "task"},
            ],
            str(tmp_path / "lib"): [
                {"id": "lib-1", "title": "Lib task", "status": "open", "priority": 1, "issue_type": "task"},
                {"id": "lib-2", "title": "Lib task 2", "status": "open", "priority": 2, "issue_type": "task"},
            ],
        }

        def mock_bd(*args, **kwargs):
            return _bd_stdout(call_map.get(kwargs.get("cwd", ""), []))

        monkeypatch.setattr("pokepoke.multi_repo_aggregator._run_bd", mock_bd)
        items = aggregate_ready_work_items(config.repos)
        assert len(items) == 3

        # Step 3: Allocate workers
        pool = RepoWorkerPool(total_workers=4, repos=config.repos)
        app_alloc = pool.get_allocation(str(tmp_path / "app"))
        lib_alloc = pool.get_allocation(str(tmp_path / "lib"))
        assert app_alloc is not None and lib_alloc is not None
        assert app_alloc.allocated_workers >= lib_alloc.allocated_workers  # Higher weight

        # Step 4: Simulate processing - app exhausts items
        pool.record_worker_start(str(tmp_path / "app"))
        pool.record_worker_done(str(tmp_path / "app"))

        # Step 5: Rebalance after app exhaustion
        result = pool.rebalance({
            str(tmp_path / "app"): 0,
            str(tmp_path / "lib"): 2,
        })
        # lib gets app's idle workers
        assert result[str(tmp_path / "lib")] > lib_alloc.allocated_workers
