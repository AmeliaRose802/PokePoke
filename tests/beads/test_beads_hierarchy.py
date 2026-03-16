"""Unit tests for beads_hierarchy module.

These tests focus on exercising the hierarchy resolution and dependency helpers so
coverage gates pass when beads_hierarchy.py is modified.
"""

from __future__ import annotations

import subprocess
from unittest.mock import Mock, patch

import pytest

from pokepoke.beads.beads_hierarchy import (
    HUMAN_REQUIRED_LABEL,
    all_children_complete,
    close_parent_if_complete,
    get_children,
    get_next_child_task,
    get_parent_id,
    has_feature_parent,
    is_assigned_to_current_user,
    is_high_conflict_risk,
    resolve_to_leaf_task,
    _get_available_children,
)
from pokepoke.types import BeadsWorkItem, Dependency, IssueWithDependencies


def _wi(
    *,
    id: str,
    issue_type: str = "task",
    status: str = "open",
    priority: int = 1,
    labels: list[str] | None = None,
    assignee: str | None = None,
) -> BeadsWorkItem:
    return BeadsWorkItem(
        id=id,
        title=id,
        description="",
        status=status,
        priority=priority,
        issue_type=issue_type,
        labels=labels,
        assignee=assignee,
    )


def test_is_high_conflict_risk() -> None:
    assert is_high_conflict_risk(_wi(id="a", labels=None)) is False
    assert is_high_conflict_risk(_wi(id="a", labels=["HIGH-CONFLICT-RISK"])) is True


@patch("pokepoke.beads.beads_hierarchy.get_issue_dependencies")
def test_get_children_handles_missing_issue(mock_get_issue: Mock) -> None:
    mock_get_issue.return_value = None
    assert get_children("epic-1") == []


@patch("pokepoke.beads.beads_hierarchy.get_issue_dependencies")
def test_get_children_filters_parent_dependents(mock_get_issue: Mock) -> None:
    mock_get_issue.side_effect = [
        IssueWithDependencies(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic",
            dependents=[
                Dependency(
                    id="task-1",
                    title="Task 1",
                    issue_type="task",
                    dependency_type="parent",
                    status="open",
                    priority=2,
                ),
                Dependency(
                    id="noise-1",
                    title="Noise",
                    issue_type="task",
                    dependency_type="blocks",
                    status="open",
                    priority=1,
                ),
            ],
        ),
        IssueWithDependencies(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=2,
            issue_type="task",
        ),
    ]

    children = get_children("epic-1")

    assert [c.id for c in children] == ["task-1"]


@pytest.mark.parametrize(
    "assignee,agent_name,status,expected",
    [
        ("agent", "agent", "in_progress", True),
        ("other", "agent", "in_progress", False),
        (None, "agent", "in_progress", False),
        (None, "agent", "open", True),
    ],
)
@patch("pokepoke.beads.beads_hierarchy._get_agent_name")
def test_is_assigned_to_current_user(
    mock_get_agent_name: Mock,
    assignee: str | None,
    agent_name: str,
    status: str,
    expected: bool,
) -> None:
    mock_get_agent_name.return_value = agent_name
    item = _wi(id="x", status=status, assignee=assignee)
    assert is_assigned_to_current_user(item) is expected


@patch("pokepoke.beads.beads_hierarchy.has_unmet_blocking_dependencies")
@patch("pokepoke.beads.beads_hierarchy.get_children")
@patch("pokepoke.beads.beads_hierarchy.is_assigned_to_current_user")
def test_get_next_child_task_filters_and_picks_priority(
    mock_is_assigned: Mock,
    mock_get_children: Mock,
    mock_has_blockers: Mock,
) -> None:
    mock_get_children.return_value = [
        _wi(id="done", status="done", priority=1),
        _wi(id="human", status="open", priority=1, labels=[HUMAN_REQUIRED_LABEL]),
        _wi(id="other", status="in_progress", priority=1),
        _wi(id="ok2", status="open", priority=2),
        _wi(id="ok1", status="open", priority=1),
    ]

    def _assigned_side_effect(item: BeadsWorkItem) -> bool:
        return item.id != "other"

    mock_is_assigned.side_effect = _assigned_side_effect
    mock_has_blockers.return_value = False

    picked = get_next_child_task("epic-1")

    assert picked is not None
    assert picked.id == "ok1"


@patch("pokepoke.beads.beads_hierarchy.has_unmet_blocking_dependencies")
@patch("pokepoke.beads.beads_hierarchy.get_children")
@patch("pokepoke.beads.beads_hierarchy.is_assigned_to_current_user")
def test_get_available_children_sorts_and_returns_all(
    mock_is_assigned: Mock,
    mock_get_children: Mock,
    mock_has_blockers: Mock,
) -> None:
    mock_is_assigned.side_effect = lambda item: item.id != "blocked"
    mock_has_blockers.return_value = False
    mock_get_children.return_value = [
        _wi(id="done", status="done", priority=1),
        _wi(id="blocked", status="open", priority=1),
        _wi(id="human", status="open", priority=1, labels=[HUMAN_REQUIRED_LABEL]),
        _wi(id="b", status="open", priority=2),
        _wi(id="a", status="open", priority=1),
    ]

    available, all_children = _get_available_children("epic-1")

    assert [c.id for c in all_children] == ["done", "blocked", "human", "b", "a"]
    assert [c.id for c in available] == ["a", "b"]


@patch("pokepoke.beads.beads_hierarchy._get_available_children")
def test_resolve_to_leaf_task_returns_leaf_directly(mock_available: Mock) -> None:
    mock_available.return_value = ([], [])
    leaf = _wi(id="t1", issue_type="task")
    assert resolve_to_leaf_task(leaf) == leaf


@patch("pokepoke.beads.beads_hierarchy._get_available_children")
def test_resolve_to_leaf_task_childless_epic_returns_item(mock_available: Mock) -> None:
    mock_available.return_value = ([], [])
    epic = _wi(id="e1", issue_type="epic")
    assert resolve_to_leaf_task(epic) == epic


@patch("pokepoke.beads.beads_hierarchy.close_parent_if_complete")
@patch("pokepoke.beads.beads_hierarchy._get_available_children")
def test_resolve_to_leaf_task_no_available_children_calls_autoclose(
    mock_available: Mock,
    mock_close_parent: Mock,
) -> None:
    mock_available.return_value = ([], [_wi(id="c1")])

    epic = _wi(id="e1", issue_type="epic")
    assert resolve_to_leaf_task(epic) is None
    mock_close_parent.assert_called_once_with("e1")


@patch("pokepoke.beads.beads_hierarchy._get_available_children")
def test_resolve_to_leaf_task_recurses_into_child_feature(mock_available: Mock) -> None:
    epic = _wi(id="epic", issue_type="epic")
    feature = _wi(id="feature", issue_type="feature", priority=1)
    leaf = _wi(id="leaf", issue_type="task", priority=1)

    def _side_effect(parent_id: str):
        if parent_id == "epic":
            return [feature], [feature]
        if parent_id == "feature":
            return [leaf], [leaf]
        raise AssertionError(parent_id)

    mock_available.side_effect = _side_effect

    resolved = resolve_to_leaf_task(epic)

    assert resolved is not None
    assert resolved.id == "leaf"


@patch("pokepoke.beads.beads_hierarchy.get_children")
def test_all_children_complete_semantics(mock_get_children: Mock) -> None:
    mock_get_children.return_value = []
    assert all_children_complete("p") is False

    mock_get_children.return_value = [_wi(id="a", status="done"), _wi(id="b", status="closed")]
    assert all_children_complete("p") is True


@patch("pokepoke.beads.beads_hierarchy.all_children_complete")
@patch("pokepoke.beads.beads_hierarchy._run_bd")
def test_close_parent_if_complete_success(mock_run_bd: Mock, mock_all_complete: Mock) -> None:
    mock_all_complete.return_value = True
    mock_run_bd.return_value = subprocess.CompletedProcess("bd", 0, stdout="")

    assert close_parent_if_complete("p") is True
    mock_run_bd.assert_called_once()


@patch("pokepoke.beads.beads_hierarchy.all_children_complete")
@patch("pokepoke.beads.beads_hierarchy.logger")
@patch("pokepoke.beads.beads_hierarchy._run_bd")
def test_close_parent_if_complete_handles_failure(
    mock_run_bd: Mock,
    mock_logger: Mock,
    mock_all_complete: Mock,
) -> None:
    mock_all_complete.return_value = True
    mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd", stderr="no")

    assert close_parent_if_complete("p") is False
    assert mock_logger.error.called


@patch("pokepoke.beads.beads_hierarchy.get_issue_dependencies")
def test_get_parent_id(mock_get_issue: Mock) -> None:
    mock_get_issue.return_value = IssueWithDependencies(
        id="c",
        title="",
        description="",
        status="open",
        priority=1,
        issue_type="task",
        dependencies=[
            Dependency(
                id="parent-1",
                title="",
                issue_type="feature",
                dependency_type="parent",
                status="open",
                priority=1,
            )
        ],
    )

    assert get_parent_id("c") == "parent-1"


@patch("pokepoke.beads.beads_hierarchy.get_issue_dependencies")
def test_has_feature_parent_true(mock_get_issue: Mock) -> None:
    mock_get_issue.return_value = IssueWithDependencies(
        id="c",
        title="",
        description="",
        status="open",
        priority=1,
        issue_type="task",
        dependencies=[
            Dependency(
                id="parent-1",
                title="",
                issue_type="feature",
                dependency_type="parent",
                status="open",
                priority=1,
            )
        ],
    )

    assert has_feature_parent("c") is True


@patch("pokepoke.beads.beads_hierarchy.logger")
@patch("pokepoke.beads.beads_hierarchy.get_issue_dependencies")
def test_has_feature_parent_handles_exception(mock_get_issue: Mock, mock_logger: Mock) -> None:
    mock_get_issue.side_effect = RuntimeError("boom")
    assert has_feature_parent("c") is False
    assert mock_logger.warning.called


@patch("pokepoke.beads.beads_hierarchy.has_unmet_blocking_dependencies")
@patch("pokepoke.beads.beads_hierarchy.get_children")
@patch("pokepoke.beads.beads_hierarchy.is_assigned_to_current_user")
def test_get_next_child_task_skips_blocked_children(
    mock_is_assigned: Mock,
    mock_get_children: Mock,
    mock_has_blockers: Mock,
) -> None:
    """Items with unmet blocking deps should be skipped by get_next_child_task."""
    mock_get_children.return_value = [
        _wi(id="blocked-child", status="open", priority=1),
        _wi(id="ok-child", status="open", priority=2),
    ]
    mock_is_assigned.return_value = True
    mock_has_blockers.side_effect = lambda item_id: item_id == "blocked-child"

    picked = get_next_child_task("epic-1")

    assert picked is not None
    assert picked.id == "ok-child"


@patch("pokepoke.beads.beads_hierarchy.has_unmet_blocking_dependencies")
@patch("pokepoke.beads.beads_hierarchy.get_children")
@patch("pokepoke.beads.beads_hierarchy.is_assigned_to_current_user")
def test_get_next_child_task_returns_none_when_all_blocked(
    mock_is_assigned: Mock,
    mock_get_children: Mock,
    mock_has_blockers: Mock,
) -> None:
    """Returns None when all children have unmet blocking deps."""
    mock_get_children.return_value = [
        _wi(id="blocked-1", status="open", priority=1),
        _wi(id="blocked-2", status="open", priority=2),
    ]
    mock_is_assigned.return_value = True
    mock_has_blockers.return_value = True

    assert get_next_child_task("epic-1") is None


@patch("pokepoke.beads.beads_hierarchy.has_unmet_blocking_dependencies")
@patch("pokepoke.beads.beads_hierarchy.get_children")
@patch("pokepoke.beads.beads_hierarchy.is_assigned_to_current_user")
def test_get_available_children_excludes_blocked_items(
    mock_is_assigned: Mock,
    mock_get_children: Mock,
    mock_has_blockers: Mock,
) -> None:
    """_get_available_children should exclude children with unmet blocking deps."""
    mock_is_assigned.return_value = True
    mock_has_blockers.side_effect = lambda item_id: item_id == "blocked-task"
    mock_get_children.return_value = [
        _wi(id="blocked-task", status="open", priority=1),
        _wi(id="ok-task", status="open", priority=2),
    ]

    available, all_children = _get_available_children("epic-1")

    assert len(all_children) == 2
    assert [c.id for c in available] == ["ok-task"]


@patch("pokepoke.beads.beads_hierarchy.has_unmet_blocking_dependencies")
@patch("pokepoke.beads.beads_hierarchy._get_available_children")
def test_resolve_to_leaf_task_skips_blocked_children(
    mock_available: Mock,
    mock_has_blockers: Mock,
) -> None:
    """resolve_to_leaf_task should not return children with unmet blocking deps.

    When _get_available_children properly filters blocked items, resolve_to_leaf_task
    should fall through to the next available child.
    """
    epic = _wi(id="epic", issue_type="epic")
    ok_leaf = _wi(id="ok-leaf", issue_type="task", priority=2)

    # _get_available_children already filters out blocked items,
    # so only ok-leaf is returned as available
    mock_available.return_value = ([ok_leaf], [ok_leaf])

    resolved = resolve_to_leaf_task(epic)

    assert resolved is not None
    assert resolved.id == "ok-leaf"
