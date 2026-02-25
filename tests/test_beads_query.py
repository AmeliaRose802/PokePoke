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
