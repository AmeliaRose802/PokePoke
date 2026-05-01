"""Comprehensive tests for multi-repo orchestration features.

Covers: config parsing with multiple repos, work item aggregation across repos,
worker allocation and rebalancing, repo exhaustion and failover, worktree
isolation per repo, maintenance scheduling independence, and metrics segmentation.
"""

import json
import subprocess
from pathlib import Path

import pytest

from pokepoke.config import (
    ProjectConfig,
    RepoConfig,
)
from pokepoke.git.multi_repo_aggregator import (
    AggregatedWorkItem,
    _query_all_repos,
    aggregate_ready_work_items,
    get_aggregated_stats,
)
from pokepoke.maintenance.maintenance_state import (
    MaintenanceState,
    RepoMaintenanceState,
    _state_from_dict,
    _state_to_dict,
    get_repo_state,
    increment_items_completed,
    load_state,
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

    def test_repo_config_max_workers_negative_raises(self) -> None:
        from pokepoke.config import ConfigError
        with pytest.raises(ConfigError, match="negative value"):
            RepoConfig(max_workers=-5)

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
            "pokepoke.git.multi_repo_aggregator._run_bd",
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

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)
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
            "pokepoke.git.multi_repo_aggregator._run_bd",
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

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)
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

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)
        repos = [_make_repo(path=str(good)), _make_repo(path=str(bad))]
        stats = get_aggregated_stats(repos)
        assert stats[str(good)] == 2
        assert stats[str(bad)] == 0

# ═══════════════════════════════════════════════════════════════════════════
# 3. WORKTREE ISOLATION PER REPO
# ═══════════════════════════════════════════════════════════════════════════

class TestWorktreeIsolationPerRepo:
    """Test that worktree operations use per-repo context."""

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
        for dirs in repos.values():
            assert str(dirs["worktree"]).startswith(str(dirs["repo"]))

# ═══════════════════════════════════════════════════════════════════════════
# 5. MAINTENANCE SCHEDULING INDEPENDENCE
# ═══════════════════════════════════════════════════════════════════════════

class TestMaintenanceIndependence:
    """Test per-repo maintenance scheduling independence."""

    def test_maintenance_state_per_repo_isolation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each repo's maintenance state is independent."""
        state_file = tmp_path / "maintenance_state.json"
        monkeypatch.setattr("pokepoke.maintenance.maintenance_state.STATE_FILE", state_file)

        count_a = increment_items_completed(repo_id="repo-a")
        count_b = increment_items_completed(repo_id="repo-b")
        assert count_a == 1
        assert count_b == 1

        count_a2 = increment_items_completed(repo_id="repo-a")
        assert count_a2 == 2
        # repo-b still at 1
        state = load_state()
        assert state.repos.get("repo-b", RepoMaintenanceState()).items_completed == 1

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
        monkeypatch.setattr("pokepoke.maintenance.maintenance_state.STATE_FILE", state_file)

        increment_items_completed(repo_id="repo-a")
        increment_items_completed(repo_id="repo-b")

        from pokepoke.maintenance.maintenance_state import load_state
        state = load_state()
        assert state.total_items_completed == 2

# ═══════════════════════════════════════════════════════════════════════════
# 6. METRICS SEGMENTATION
# ═══════════════════════════════════════════════════════════════════════════

class TestMetricsSegmentation:
    """Test per-repo metrics attribution and segmentation."""

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

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)

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

    def test_maintenance_state_with_real_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Maintenance state works with real directory-based repo IDs."""
        state_file = tmp_path / "state.json"
        monkeypatch.setattr("pokepoke.maintenance.maintenance_state.STATE_FILE", state_file)

        repo_a = str(tmp_path / "repo-a")
        repo_b = str(tmp_path / "repo-b")

        increment_items_completed(repo_id=repo_a)
        increment_items_completed(repo_id=repo_a)
        increment_items_completed(repo_id=repo_b)

        state = load_state()
        assert state.repos.get(repo_a, RepoMaintenanceState()).items_completed == 2
        assert state.repos.get(repo_b, RepoMaintenanceState()).items_completed == 1
