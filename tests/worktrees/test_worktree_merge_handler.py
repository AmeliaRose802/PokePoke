"""Tests for worktree merge handling — perform_worktree_merge and handle_worktree_merge."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.types import BeadsWorkItem
from pokepoke.worktrees.worktree_merge_handler import handle_worktree_merge, perform_worktree_merge


def _make_agent_item(item_id: str = "maintenance-test") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title="Maintenance item",
        status="ready",
        priority=1,
        issue_type="task",
    )


# ---------------------------------------------------------------------------
# Tests for handle_worktree_merge (the public entry-point with merge-lock)
# ---------------------------------------------------------------------------


@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_cleanup_agent")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
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


@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_cleanup_agent")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
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


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
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
    mock_is_merge_in_progress.side_effect = [True, True]
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
    mock_invoke_conflict_cleanup.assert_called_once()
    mock_abort_merge.assert_called_once()


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
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


# ---------------------------------------------------------------------------
# Tests for perform_worktree_merge (the core shared logic)
# ---------------------------------------------------------------------------


@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_first_merge_succeeds(
    mock_check, mock_merge, mock_add, mock_remove,
) -> None:
    """Direct success on first merge attempt."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = (True, [])

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is True
    assert cleaned is True
    mock_add.assert_not_called()


@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_cleanup_agent")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_pre_merge_cleanup_fails(
    mock_check, mock_cleanup, mock_add,
) -> None:
    """Pre-merge cleanup failure returns (False, False)."""
    mock_check.return_value = (False, "dirty")
    mock_cleanup.return_value = (False, None)

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is False
    assert cleaned is False
    mock_add.assert_called_once()


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_abort_merge_failure_returns_false(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging, mock_abort,
) -> None:
    """When abort_merge fails after cleanup, return (False, False)."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = (False, ["file.py"])
    mock_is_merging.return_value = True
    mock_get_unmerged.return_value = ["file.py"]
    mock_conflict_cleanup.return_value = (True, None)
    mock_abort.return_value = (False, "Cannot abort")

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()
    assert mock_merge.call_count == 1


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_retry_merge_succeeds_after_cleanup(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging, mock_abort,
) -> None:
    """Retry merge succeeds when cleanup resolves merge state."""
    mock_check.return_value = (True, "")
    mock_merge.side_effect = [(False, ["file.py"]), (True, [])]
    mock_is_merging.side_effect = [True, False]
    mock_get_unmerged.return_value = ["file.py"]
    mock_conflict_cleanup.return_value = (True, None)

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is True
    assert cleaned is True
    mock_abort.assert_not_called()
    mock_remove.assert_called_once_with("item-1")


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_retry_merge_fails_aborts(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging, mock_abort,
) -> None:
    """Retry merge failure triggers abort when merge still in progress."""
    mock_check.return_value = (True, "")
    mock_merge.side_effect = [(False, ["f.py"]), (False, ["f.py"])]
    mock_is_merging.side_effect = [True, False, True]
    mock_get_unmerged.return_value = ["f.py"]
    mock_conflict_cleanup.return_value = (True, None)
    mock_abort.return_value = (True, "")

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_cleanup_failure_no_abort_when_not_merging(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add,
    mock_is_merging, mock_abort,
) -> None:
    """No abort when cleanup fails and not in merge state."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = (False, ["file.py"])
    mock_is_merging.side_effect = [True, False]
    mock_conflict_cleanup.return_value = (False, None)

    success, _ = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is False
    mock_abort.assert_not_called()


@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_conflict_details_in_cleanup_prompt(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging,
) -> None:
    """Verify conflict_details with file list is passed to cleanup agent."""
    mock_check.return_value = (True, "")
    files = ["src/a.py", "src/b.py", "tests/c.py"]
    mock_merge.side_effect = [(False, files), (True, [])]
    mock_is_merging.side_effect = [True, False]
    mock_get_unmerged.return_value = files
    mock_conflict_cleanup.return_value = (True, None)

    perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )

    call_args = mock_conflict_cleanup.call_args
    error_msg = call_args[0][1]
    assert "Conflicted Files" in error_msg
    assert "src/a.py" in error_msg
    assert call_args.kwargs["unmerged_files"] == files


@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_handles_many_conflict_files(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging,
) -> None:
    """15+ files should all be included in the cleanup prompt."""
    mock_check.return_value = (True, "")
    many_files = [f"src/module{i}.py" for i in range(15)]
    mock_merge.side_effect = [(False, many_files), (True, [])]
    mock_is_merging.side_effect = [True, False]
    mock_get_unmerged.return_value = many_files
    mock_conflict_cleanup.return_value = (True, None)

    perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )

    call_kwargs = mock_conflict_cleanup.call_args
    assert len(call_kwargs.kwargs["unmerged_files"]) == 15


@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_fetches_fresh_unmerged_when_not_merging(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add,
    mock_get_unmerged, mock_is_merging,
) -> None:
    """get_unmerged_files called when merge fails without merge-in-progress."""
    mock_check.return_value = (True, "")
    mock_merge.side_effect = [(False, []), (True, [])]
    mock_is_merging.return_value = False
    mock_get_unmerged.return_value = ["stale.py"]
    mock_conflict_cleanup.return_value = (True, None)

    success, _ = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is True
    mock_get_unmerged.assert_called_once()


@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_first_merge_worktree_persists(
    mock_check, mock_merge, mock_add,
    mock_get_unmerged, mock_is_merging, tmp_path,
) -> None:
    """Worktree directory persisting after merge reports cleaned=False."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = (True, [])

    # Create a real directory that simulates a worktree not cleaned up
    worktree_dir = tmp_path / "task-item-1"
    worktree_dir.mkdir()

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        worktree_dir, tmp_path,
    )
    assert success is True
    assert cleaned is False
    mock_add.assert_called_once()
    assert "persists" in mock_add.call_args[0][2].lower()


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_retry_abort_failure_logs_error(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging, mock_abort,
) -> None:
    """When abort_merge fails after retry merge failure, return (False, False) with error logged."""
    mock_check.return_value = (True, "")
    mock_merge.side_effect = [(False, ["f.py"]), (False, ["f.py"])]
    mock_is_merging.side_effect = [True, False, True]
    mock_get_unmerged.return_value = ["f.py"]
    mock_conflict_cleanup.return_value = (True, None)
    mock_abort.return_value = (False, "Cannot abort: lock held")

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_cleanup_failure_abort_failure_logged(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add,
    mock_is_merging, mock_abort,
) -> None:
    """When abort_merge fails after cleanup failure, error is logged but function returns."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = (False, ["file.py"])
    mock_is_merging.side_effect = [True, True]
    mock_conflict_cleanup.return_value = (False, None)
    mock_abort.return_value = (False, "Cannot abort")

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        Path("C:/wt"), Path("C:/repo"),
    )
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_retry_merge_worktree_persists(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging, mock_abort, tmp_path,
) -> None:
    """Retry merge succeeds but worktree directory persists — cleaned=False."""
    mock_check.return_value = (True, "")
    mock_merge.side_effect = [(False, ["file.py"]), (True, [])]
    mock_is_merging.side_effect = [True, False]
    mock_get_unmerged.return_value = ["file.py"]
    mock_conflict_cleanup.return_value = (True, None)

    worktree_dir = tmp_path / "task-item-1"
    worktree_dir.mkdir()

    success, cleaned = perform_worktree_merge(
        "item-1", _make_agent_item("item-1"),
        worktree_dir, tmp_path,
    )
    assert success is True
    assert cleaned is False
    # Should track in manifest since worktree persists
    mock_add.assert_called()
    # remove_from_manifest still called (from conflict tracking), then re-added for persistence
    mock_remove.assert_called_once_with("item-1")
@pytest.fixture(autouse=True)
def _mock_cleanup_lock(monkeypatch):
    """Ensure cleanup lock is a no-op for tests."""
    monkeypatch.setattr(
        "pokepoke.worktrees.worktree_merge_handler.cleanup_lock",
        lambda: nullcontext(),
    )


@pytest.fixture(autouse=True)
def _mock_merge_lock(monkeypatch):
    """Ensure merge lock is a no-op for tests."""
    monkeypatch.setattr(
        "pokepoke.worktrees.worktree_merge_handler.merge_lock",
        lambda: nullcontext(),
    )


# ---------------------------------------------------------------------------
# Tests for handle_worktree_merge lock timeout and exception paths
# ---------------------------------------------------------------------------


def test_handle_worktree_merge_lock_timeout(monkeypatch) -> None:
    """Merge lock timeout adds to manifest and returns (False, False) (lines 61-71)."""
    from filelock import Timeout

    # Override merge_lock to raise Timeout
    def raise_timeout():
        raise Timeout("lock_file")

    class TimeoutCtx:
        def __enter__(self):
            raise Timeout("lock_file")
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "pokepoke.worktrees.worktree_merge_handler.merge_lock",
        lambda: TimeoutCtx(),
    )

    with patch("pokepoke.worktrees.worktree_merge_handler.add_uncleaned_worktree") as mock_add, \
         patch("builtins.print"):

        agent_item = _make_agent_item()
        success, cleaned = handle_worktree_merge(
            agent_id=agent_item.id,
            agent_item=agent_item,
            agent_name="Janitor",
            worktree_path=Path("C:/worktrees/task-test"),
            repo_root=Path("C:/repo"),
            agent_stats=None,
        )

        assert success is False
        assert cleaned is False
        mock_add.assert_called_once()
        assert "timeout" in mock_add.call_args[0][2].lower()


def test_handle_worktree_merge_unexpected_exception(monkeypatch) -> None:
    """Unexpected exception during merge adds to manifest and returns (False, False) (lines 72-81)."""
    class ErrorCtx:
        def __enter__(self):
            raise RuntimeError("unexpected disk error")
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "pokepoke.worktrees.worktree_merge_handler.merge_lock",
        lambda: ErrorCtx(),
    )

    with patch("pokepoke.worktrees.worktree_merge_handler.add_uncleaned_worktree") as mock_add, \
         patch("builtins.print"):

        agent_item = _make_agent_item()
        success, cleaned = handle_worktree_merge(
            agent_id=agent_item.id,
            agent_item=agent_item,
            agent_name="Janitor",
            worktree_path=Path("C:/worktrees/task-test"),
            repo_root=Path("C:/repo"),
            agent_stats=None,
        )

        assert success is False
        assert cleaned is False
        mock_add.assert_called_once()
        assert "unexpected disk error" in mock_add.call_args[0][2].lower()
