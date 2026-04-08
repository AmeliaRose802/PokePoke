"""Tests for multi-repo work item aggregator."""

import json
import subprocess
from pathlib import Path

import pytest

from pokepoke.config import RepoConfig
from pokepoke.git.multi_repo_aggregator import (
    AggregatedWorkItem,
    RepoQueryResult,
    _derive_repo_name,
    _merge_and_sort,
    aggregate_ready_work_items,
    get_aggregated_stats,
    query_repo_ready_items,
)
from pokepoke.types import BeadsWorkItem

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
) -> RepoConfig:
    return RepoConfig(path=path, priority_weight=priority_weight, enabled=enabled)


def _bd_stdout(items: list[dict]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess("bd", 0, stdout=json.dumps(items))


# ---------------------------------------------------------------------------
# _derive_repo_name
# ---------------------------------------------------------------------------

class TestDeriveRepoName:
    def test_extracts_last_path_component(self) -> None:
        rc = _make_repo(path="/home/user/projects/my-lib")
        assert _derive_repo_name(rc) == "my-lib"

    def test_empty_path_returns_empty(self) -> None:
        rc = _make_repo(path="")
        assert _derive_repo_name(rc) == ""

    def test_windows_path(self) -> None:
        rc = _make_repo(path="C:\\Users\\dev\\PokePoke")
        name = _derive_repo_name(rc)
        assert name == "PokePoke"


# ---------------------------------------------------------------------------
# query_repo_ready_items
# ---------------------------------------------------------------------------

class TestQueryRepoReadyItems:
    def test_disabled_repo_returns_empty(self) -> None:
        result = query_repo_ready_items(_make_repo(enabled=False))
        assert result.items == []
        assert result.error is None

    def test_empty_path_returns_error(self) -> None:
        result = query_repo_ready_items(_make_repo(path=""))
        assert result.error is not None
        assert "empty" in result.error.lower()

    def test_nonexistent_path_returns_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "does_not_exist"
        result = query_repo_ready_items(_make_repo(path=str(bad)))
        assert result.error is not None
        assert "does not exist" in result.error

    def test_successful_query(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        payload = [
            {"id": "a1", "title": "T", "status": "open", "priority": 1, "issue_type": "task"},
        ]
        monkeypatch.setattr(
            "pokepoke.git.multi_repo_aggregator._run_bd",
            lambda *a, **kw: _bd_stdout(payload),
        )
        result = query_repo_ready_items(_make_repo(path=str(tmp_path)))
        assert len(result.items) == 1
        assert result.items[0].id == "a1"
        assert result.error is None

    def test_handles_bd_failure(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        def boom(*_a: object, **_kw: object) -> None:
            raise subprocess.CalledProcessError(1, "bd")

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", boom)
        result = query_repo_ready_items(_make_repo(path=str(tmp_path)))
        assert result.items == []
        assert result.error is not None

    def test_handles_empty_stdout(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(
            "pokepoke.git.multi_repo_aggregator._run_bd",
            lambda *a, **kw: subprocess.CompletedProcess("bd", 0, stdout=""),
        )
        result = query_repo_ready_items(_make_repo(path=str(tmp_path)))
        assert result.items == []
        assert result.error is None

    def test_handles_malformed_json(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(
            "pokepoke.git.multi_repo_aggregator._run_bd",
            lambda *a, **kw: subprocess.CompletedProcess("bd", 0, stdout="[{bad json}]"),
        )
        result = query_repo_ready_items(_make_repo(path=str(tmp_path)))
        assert result.items == []
        # Malformed JSON is treated as empty output (no error set)

    def test_passes_cwd_to_bd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        captured_cwd: list[str | None] = []

        def capture_bd(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured_cwd.append(kwargs.get("cwd"))
            return subprocess.CompletedProcess("bd", 0, stdout="[]")

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", capture_bd)
        query_repo_ready_items(_make_repo(path=str(tmp_path)))
        assert captured_cwd[0] == str(tmp_path)


# ---------------------------------------------------------------------------
# _merge_and_sort
# ---------------------------------------------------------------------------

class TestMergeAndSort:
    def test_empty_results(self) -> None:
        assert _merge_and_sort([]) == []

    def test_error_results_excluded(self) -> None:
        result = RepoQueryResult(repo_config=_make_repo(), error="fail")
        assert _merge_and_sort([result]) == []

    def test_higher_weight_repo_items_first(self) -> None:
        low = RepoQueryResult(
            repo_config=_make_repo(path="/low", priority_weight=1),
            items=[_make_item("low-1", priority=0)],
        )
        high = RepoQueryResult(
            repo_config=_make_repo(path="/high", priority_weight=10),
            items=[_make_item("high-1", priority=0)],
        )
        merged = _merge_and_sort([low, high])
        assert len(merged) == 2
        assert merged[0].item.id == "high-1"
        assert merged[1].item.id == "low-1"

    def test_within_repo_sorts_by_item_priority(self) -> None:
        r = RepoQueryResult(
            repo_config=_make_repo(path="/repo"),
            items=[
                _make_item("p3", priority=3),
                _make_item("p1", priority=1),
                _make_item("p0", priority=0),
            ],
        )
        merged = _merge_and_sort([r])
        assert [a.item.id for a in merged] == ["p0", "p1", "p3"]

    def test_stable_ordering_by_id(self) -> None:
        r = RepoQueryResult(
            repo_config=_make_repo(path="/repo"),
            items=[
                _make_item("b", priority=1),
                _make_item("a", priority=1),
            ],
        )
        merged = _merge_and_sort([r])
        assert [a.item.id for a in merged] == ["a", "b"]

    def test_repo_context_preserved(self) -> None:
        r = RepoQueryResult(
            repo_config=_make_repo(path="/projects/my-lib", priority_weight=5),
            items=[_make_item("x")],
        )
        merged = _merge_and_sort([r])
        assert merged[0].repo_path == "/projects/my-lib"
        assert merged[0].repo_name == "my-lib"
        assert merged[0].repo_priority_weight == 5


# ---------------------------------------------------------------------------
# aggregate_ready_work_items
# ---------------------------------------------------------------------------

class TestAggregateReadyWorkItems:
    def test_no_repos_returns_empty(self) -> None:
        assert aggregate_ready_work_items([]) == []

    def test_all_disabled_returns_empty(self) -> None:
        repos = [_make_repo(enabled=False), _make_repo(enabled=False)]
        assert aggregate_ready_work_items(repos) == []

    def test_single_repo(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        payload = [
            {"id": "t1", "title": "T", "status": "open", "priority": 2, "issue_type": "task"},
        ]
        monkeypatch.setattr(
            "pokepoke.git.multi_repo_aggregator._run_bd",
            lambda *a, **kw: _bd_stdout(payload),
        )
        items = aggregate_ready_work_items([_make_repo(path=str(tmp_path))])
        assert len(items) == 1
        assert items[0].item.id == "t1"

    def test_multiple_repos_priority_weighted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        repo_a.mkdir()
        repo_b.mkdir()

        call_map = {
            str(repo_a): [{"id": "a1", "title": "A", "status": "open", "priority": 1, "issue_type": "task"}],
            str(repo_b): [{"id": "b1", "title": "B", "status": "open", "priority": 1, "issue_type": "task"}],
        }

        def mock_bd(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            cwd = kwargs.get("cwd", "")
            payload = call_map.get(cwd, [])
            return _bd_stdout(payload)

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)

        repos = [
            _make_repo(path=str(repo_a), priority_weight=1),
            _make_repo(path=str(repo_b), priority_weight=10),
        ]
        items = aggregate_ready_work_items(repos)
        assert len(items) == 2
        # Higher weight repo_b should be first
        assert items[0].item.id == "b1"
        assert items[1].item.id == "a1"

    def test_tolerates_repo_with_no_items(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo_a = tmp_path / "has_items"
        repo_b = tmp_path / "empty"
        repo_a.mkdir()
        repo_b.mkdir()

        call_map = {
            str(repo_a): [{"id": "x", "title": "X", "status": "open", "priority": 1, "issue_type": "task"}],
            str(repo_b): [],
        }

        def mock_bd(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            cwd = kwargs.get("cwd", "")
            return _bd_stdout(call_map.get(cwd, []))

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)

        repos = [_make_repo(path=str(repo_a)), _make_repo(path=str(repo_b))]
        items = aggregate_ready_work_items(repos)
        assert len(items) == 1

    def test_tolerates_repo_with_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        good = tmp_path / "good"
        bad = tmp_path / "bad"
        good.mkdir()
        bad.mkdir()

        def mock_bd(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            cwd = kwargs.get("cwd", "")
            if "bad" in cwd:
                raise subprocess.CalledProcessError(1, "bd")
            return _bd_stdout([
                {"id": "g1", "title": "Good", "status": "open", "priority": 1, "issue_type": "task"},
            ])

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)

        repos = [_make_repo(path=str(good)), _make_repo(path=str(bad))]
        items = aggregate_ready_work_items(repos)
        assert len(items) == 1
        assert items[0].item.id == "g1"


# ---------------------------------------------------------------------------
# get_aggregated_stats
# ---------------------------------------------------------------------------

class TestGetAggregatedStats:
    def test_returns_counts_per_repo(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()

        call_map = {
            str(repo_a): [
                {"id": "a1", "title": "A", "status": "open", "priority": 1, "issue_type": "task"},
                {"id": "a2", "title": "B", "status": "open", "priority": 2, "issue_type": "task"},
            ],
            str(repo_b): [],
        }

        def mock_bd(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            cwd = kwargs.get("cwd", "")
            return _bd_stdout(call_map.get(cwd, []))

        monkeypatch.setattr("pokepoke.git.multi_repo_aggregator._run_bd", mock_bd)

        repos = [_make_repo(path=str(repo_a)), _make_repo(path=str(repo_b))]
        stats = get_aggregated_stats(repos)
        assert stats[str(repo_a)] == 2
        assert stats[str(repo_b)] == 0

    def test_skips_disabled_repos(self) -> None:
        repos = [_make_repo(path="/x", enabled=False)]
        stats = get_aggregated_stats(repos)
        assert stats == {}


# ---------------------------------------------------------------------------
# RepoConfig validation
# ---------------------------------------------------------------------------

class TestRepoConfig:
    def test_default_values(self) -> None:
        rc = RepoConfig()
        assert rc.path == ""
        assert rc.priority_weight == 1
        assert rc.enabled is True

    def test_priority_weight_clamped(self) -> None:
        rc = RepoConfig(priority_weight=0)
        assert rc.priority_weight == 1

    def test_priority_weight_negative_raises(self) -> None:
        from pokepoke.config import ConfigError
        with pytest.raises(ConfigError, match="negative value"):
            RepoConfig(priority_weight=-5)

    def test_custom_values(self) -> None:
        rc = RepoConfig(path="/my/repo", priority_weight=10, enabled=False)
        assert rc.path == "/my/repo"
        assert rc.priority_weight == 10
        assert rc.enabled is False


# ---------------------------------------------------------------------------
# AggregatedWorkItem
# ---------------------------------------------------------------------------

class TestAggregatedWorkItem:
    def test_construction(self) -> None:
        item = _make_item("test")
        agg = AggregatedWorkItem(
            item=item,
            repo_path="/repo",
            repo_name="repo",
            repo_priority_weight=5,
        )
        assert agg.item.id == "test"
        assert agg.repo_path == "/repo"
        assert agg.repo_name == "repo"
        assert agg.repo_priority_weight == 5

    def test_defaults(self) -> None:
        item = _make_item("test")
        agg = AggregatedWorkItem(item=item, repo_path="/r")
        assert agg.repo_name == ""
        assert agg.repo_priority_weight == 1
