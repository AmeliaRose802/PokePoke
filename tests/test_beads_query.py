import json
import subprocess
from pathlib import Path

import pytest

from pokepoke import beads_query
from pokepoke.types import Dependency, IssueWithDependencies


def test_parse_beads_json_filters_prefixes() -> None:
    output = "Note: info\nWarning: skip\nHint: also skip\nCreated item\n{\n  \"value\": 1\n}\n"
    parsed = beads_query._parse_beads_json(output, extra_prefixes=("Created",))
    assert parsed == {"value": 1}


def test_parse_beads_json_returns_none_when_no_json() -> None:
    assert beads_query._parse_beads_json("no json here") is None


def test_get_ready_work_items_parses_results(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"id": "x", "title": "Task", "status": "open", "priority": 1, "issue_type": "task", "description": "d"},
    ]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    items = beads_query.get_ready_work_items()

    assert len(items) == 1
    assert items[0].id == "x"


def test_get_ready_work_items_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_ready_work_items() == []


def test_get_issue_dependencies_returns_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": "A",
            "title": "Issue A",
            "status": "open",
            "priority": 1,
            "issue_type": "task",
            "dependencies": [
                {"id": "dep1", "title": "Dep", "issue_type": "task", "dependency_type": "blocks", "status": "open"}
            ],
        }
    ]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    issue = beads_query.get_issue_dependencies("A")

    assert issue is not None
    assert issue.dependencies and isinstance(issue.dependencies[0], Dependency)
    assert issue.dependencies[0].dependency_type == "blocks"


def test_has_unmet_blocking_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    deps = [Dependency(id="d1", title="", issue_type="task", dependency_type="blocks", status="open")]
    issue = IssueWithDependencies(id="A", title="", status="open", priority=1, issue_type="task", dependencies=deps)
    monkeypatch.setattr(beads_query, "get_issue_dependencies", lambda _item_id: issue)

    assert beads_query.has_unmet_blocking_dependencies("A") is True

    deps[0].status = "closed"
    assert beads_query.has_unmet_blocking_dependencies("A") is False


def test_get_beads_stats_parses_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    stats_json = {"summary": {"total_issues": 5, "open_issues": 2, "in_progress_issues": 1, "closed_issues": 2, "ready_issues": 3}}
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(stats_json))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)
    monkeypatch.setattr(beads_query, "_get_main_repo_root", lambda: Path("/repo"))

    stats = beads_query.get_beads_stats()

    assert stats is not None
    assert stats.total_issues == 5
    assert stats.ready_issues == 3


def test_get_beads_stats_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("bd missing")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_beads_stats() is None


def test_get_main_repo_root_returns_none_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import pokepoke.git_operations

    def boom() -> None:
        raise RuntimeError("not a repo")

    monkeypatch.setattr(pokepoke.git_operations, "get_main_repo_root", boom)

    assert beads_query._get_main_repo_root() is None


def test_run_bd_uses_lock_for_mutating_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {"lock_timeout": None, "ran": False}

    class _Lock:
        def __init__(self, *, timeout: float):
            calls["lock_timeout"] = timeout

        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_lock(*, timeout: float):
        return _Lock(timeout=timeout)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["ran"] = True
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    monkeypatch.setattr(beads_query, "beads_db_lock", fake_lock)
    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    beads_query._run_bd(["update", "x"], check=False)

    assert calls["ran"] is True
    assert calls["lock_timeout"] == 180.0


def test_run_bd_skips_lock_for_non_mutating_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_called = {"called": False}

    def fake_lock(*, timeout: float):
        lock_called["called"] = True
        raise AssertionError("should not lock")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="[]")

    monkeypatch.setattr(beads_query, "beads_db_lock", fake_lock)
    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    beads_query._run_bd(["ready", "--json"], check=False)

    assert lock_called["called"] is False


def test_filter_to_dataclass_filters_extraneous_fields() -> None:
    import dataclasses

    @dataclasses.dataclass
    class _X:
        a: int
        b: str

    inst = beads_query._filter_to_dataclass(_X, {"a": 1, "b": "ok", "extra": 2})
    assert inst == _X(a=1, b="ok")


def test_get_issue_dependencies_returns_none_on_calledprocesserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_empty_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="not valid json {{{")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="[]")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_non_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout='{"id": "A"}')
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("bd", 30)

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("unexpected")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_converts_dependents(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": "A",
            "title": "Issue A",
            "status": "open",
            "priority": 1,
            "issue_type": "task",
            "dependents": [
                {"id": "child1", "title": "Child", "issue_type": "task", "dependency_type": "parent", "status": "open"}
            ],
        }
    ]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    issue = beads_query.get_issue_dependencies("A")

    assert issue is not None
    assert issue.dependents is not None
    assert issue.dependents[0].dependency_type == "parent"


# ── is_beads_item_closed ────────────────────────────────────────────


def test_is_beads_item_closed_returns_true_for_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "closed", "title": "Done"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is True


def test_is_beads_item_closed_returns_false_for_open(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "open", "title": "Active"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_for_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "in_progress", "title": "Working"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("bd", 30)

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_on_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_handles_non_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"id": "x", "status": "closed", "title": "Done"}
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is True


def test_is_beads_item_closed_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "Closed", "title": "Done"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is True
