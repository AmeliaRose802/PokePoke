"""Tests for handle_worktree_merge cleanup retry behavior."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.types import BeadsWorkItem
from pokepoke.worktree_merge_handler import handle_worktree_merge


def _make_agent_item() -> BeadsWorkItem:
    return BeadsWorkItem(
        id="maintenance-test",
        title="Maintenance item",
        status="ready",
        priority=1,
        issue_type="task",
    )


@patch("pokepoke.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktree_merge_handler.merge_worktree")
@patch("pokepoke.worktree_merge_handler.invoke_cleanup_agent")
@patch("pokepoke.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.git_operations.check_main_repo_ready_for_merge")
def test_handle_worktree_merge_retries_after_successful_cleanup(
    mock_check_ready,
    mock_add_manifest,
    mock_invoke_cleanup,
    mock_merge_worktree,
    mock_remove_from_manifest,
) -> None:
    """Cleanup success should allow merge to proceed."""
    mock_check_ready.side_effect = [(False, "dirty state"), (True, "")]
    mock_invoke_cleanup.return_value = (True, None)
    mock_merge_worktree.return_value = (True, [])

    agent_item = _make_agent_item()
    success, cleaned = handle_worktree_merge(
        agent_id=agent_item.id,
        agent_item=agent_item,
        agent_name="Janitor",
        worktree_path=Path("C:/worktrees/task-maintenance-test"),
        repo_root=Path("C:/repo"),
        agent_stats=None,
    )

    assert success is True
    assert cleaned is True
    assert mock_merge_worktree.call_count == 1
    mock_remove_from_manifest.assert_called_once_with(agent_item.id)
    mock_add_manifest.assert_called_once()  # ensure manifest still tracks preserved state before cleanup


@patch("pokepoke.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktree_merge_handler.merge_worktree")
@patch("pokepoke.worktree_merge_handler.invoke_cleanup_agent")
@patch("pokepoke.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.git_operations.check_main_repo_ready_for_merge")
def test_handle_worktree_merge_cleanup_retry_respects_second_failure(
    mock_check_ready,
    mock_add_manifest,
    mock_invoke_cleanup,
    mock_merge_worktree,
    mock_remove_from_manifest,
) -> None:
    """If the repo is still not ready after cleanup, we should exit early."""
    mock_check_ready.side_effect = [(False, "dirty state"), (False, "still dirty")]
    mock_invoke_cleanup.return_value = (True, None)

    agent_item = _make_agent_item()
    success, cleaned = handle_worktree_merge(
        agent_id=agent_item.id,
        agent_item=agent_item,
        agent_name="Janitor",
        worktree_path=Path("C:/worktrees/task-maintenance-test"),
        repo_root=Path("C:/repo"),
        agent_stats=None,
    )

    assert success is False
    assert cleaned is False
    mock_merge_worktree.assert_not_called()
    mock_remove_from_manifest.assert_not_called()
    mock_add_manifest.assert_called_once()


@patch("pokepoke.git_operations.abort_merge")
@patch("pokepoke.git_operations.is_merge_in_progress")
@patch("pokepoke.git_operations.get_unmerged_files")
@patch("pokepoke.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git_operations.check_main_repo_ready_for_merge")
def test_handle_worktree_merge_conflict_cleanup_retry_succeeds(
    mock_check_ready,
    mock_merge_worktree,
    mock_invoke_conflict_cleanup,
    mock_add_manifest,
    mock_remove_manifest,
    mock_get_unmerged_files,
    mock_is_merge_in_progress,
    mock_abort_merge,
) -> None:
    """Ensure merge-conflict path retries and cleans manifest on success."""
    mock_check_ready.return_value = (True, "")
    mock_merge_worktree.side_effect = [(False, []), (True, [])]
    mock_invoke_conflict_cleanup.return_value = (True, None)
    mock_get_unmerged_files.return_value = ["conflict.txt"]
    mock_is_merge_in_progress.side_effect = [True]
    mock_abort_merge.return_value = (True, "")

    agent_item = _make_agent_item()
    success, cleaned = handle_worktree_merge(
        agent_id=agent_item.id,
        agent_item=agent_item,
        agent_name="Janitor",
        worktree_path=Path("C:/worktrees/task-maintenance-test"),
        repo_root=Path("C:/repo"),
        agent_stats=None,
    )

    assert success is True
    assert cleaned is True
    assert mock_merge_worktree.call_count == 2
    mock_add_manifest.assert_called_once()
    mock_remove_manifest.assert_called_once_with(agent_item.id)
    mock_get_unmerged_files.assert_called_once()
    mock_invoke_conflict_cleanup.assert_called_once()
    mock_abort_merge.assert_called_once()


@patch("pokepoke.git_operations.abort_merge")
@patch("pokepoke.git_operations.is_merge_in_progress")
@patch("pokepoke.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git_operations.check_main_repo_ready_for_merge")
def test_handle_worktree_merge_conflict_cleanup_failure(
    mock_check_ready,
    mock_merge_worktree,
    mock_invoke_conflict_cleanup,
    mock_add_manifest,
    mock_remove_manifest,
    mock_is_merge_in_progress,
    mock_abort_merge,
) -> None:
    """If conflict cleanup fails we should abort and report failure."""
    mock_check_ready.return_value = (True, "")
    mock_merge_worktree.return_value = (False, ["conflict.txt"])
    mock_invoke_conflict_cleanup.return_value = (False, None)
    mock_is_merge_in_progress.return_value = True

    agent_item = _make_agent_item()
    success, cleaned = handle_worktree_merge(
        agent_id=agent_item.id,
        agent_item=agent_item,
        agent_name="Janitor",
        worktree_path=Path("C:/worktrees/task-maintenance-test"),
        repo_root=Path("C:/repo"),
        agent_stats=None,
    )

    assert success is False
    assert cleaned is False
    mock_merge_worktree.assert_called_once()
    mock_add_manifest.assert_called_once()
    mock_remove_manifest.assert_not_called()
    mock_invoke_conflict_cleanup.assert_called_once()
    mock_abort_merge.assert_called_once()
@pytest.fixture(autouse=True)
def _mock_cleanup_lock(monkeypatch):
    """Ensure cleanup lock is a no-op for tests."""
    monkeypatch.setattr(
        "pokepoke.worktree_merge_handler.cleanup_lock",
        lambda: nullcontext(),
    )


@pytest.fixture(autouse=True)
def _mock_merge_lock(monkeypatch):
    """Ensure merge lock is a no-op for tests."""
    monkeypatch.setattr(
        "pokepoke.worktree_merge_handler.merge_lock",
        lambda: nullcontext(),
    )
