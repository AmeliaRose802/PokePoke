"""Tests for worktree merge handling — perform_worktree_merge and handle_worktree_merge."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.types import BeadsWorkItem
from pokepoke.worktrees.worktree_merge_handler import (
    _ConflictResolutionNeeded,
    WorktreeMergeContext,
    handle_worktree_merge,
    perform_worktree_merge,
)
from pokepoke.worktrees.merge_conflict_retry import retry_merge_after_cleanup
from pokepoke.worktrees.merge_step_tracker import get_merge_step_tracker
from pokepoke.worktrees.worktrees import MergeResult


def _make_agent_item(item_id: str = "maintenance-test") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title="Maintenance item",
        status="ready",
        priority=1,
        issue_type="task",
    )


def _make_merge_context(
    agent_id: str = "maintenance-test",
    agent_name: str = "Janitor",
    worktree_path: Path = Path("C:/worktrees/task-maintenance-test"),
    repo_root: Path = Path("C:/repo"),
    parent_agent_id: str | None = None,
    repo_path: str | None = None,
) -> WorktreeMergeContext:
    """Helper to create a WorktreeMergeContext for testing."""
    return WorktreeMergeContext(
        agent_id=agent_id,
        agent_item=_make_agent_item(agent_id),
        agent_name=agent_name,
        worktree_path=worktree_path,
        repo_root=repo_root,
        parent_agent_id=parent_agent_id,
        repo_path=repo_path,
    )


@pytest.fixture(autouse=True)
def _mock_prelock_checks(monkeypatch):
    """Auto-mock the pre-lock worktree checks so handle_worktree_merge tests
    can focus on the under-lock logic.  is_worktree_clean returns True and
    the commit-count git rev-list returns 1 (non-zero → proceed to merge).
    """
    monkeypatch.setattr(
        "pokepoke.worktrees.worktree_merge_handler.is_worktree_clean",
        lambda _path: True,
    )
    monkeypatch.setattr(
        "pokepoke.worktrees.worktree_merge_handler.get_default_branch",
        lambda **_kw: "master",
    )
    monkeypatch.setattr(
        "pokepoke.git.git_helpers.subprocess.run",
        lambda cmd, **kw: Mock(stdout="1\n", stderr="", returncode=0),
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
    mock_merge_worktree.return_value = MergeResult(success=True)

    success, cleaned = handle_worktree_merge(
        _make_merge_context(),
        agent_stats=None,
    )

    assert success is True
    assert cleaned is True
    assert mock_merge_worktree.call_count == 1
    mock_remove_from_manifest.assert_called_once_with("maintenance-test")
    mock_add_manifest.assert_called_once()  # ensure manifest still tracks preserved state before cleanup


@patch("pokepoke.utils.shutdown.request_shutdown")
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
    mock_shutdown,
) -> None:
    """If repo stays dirty after all 3 cleanup retries, halt the orchestrator."""
    # First check fails, then all re-checks after cleanup also fail
    mock_check_ready.side_effect = [(False, "dirty state")] + [(False, "still dirty")] * 3
    mock_invoke_cleanup.return_value = (True, None)

    success, cleaned = handle_worktree_merge(
        _make_merge_context(),
        agent_stats=None,
    )

    assert success is False
    assert cleaned is False
    mock_merge_worktree.assert_not_called()
    mock_remove_from_manifest.assert_not_called()
    assert mock_invoke_cleanup.call_count == 3, "Should retry cleanup 3 times"
    mock_shutdown.assert_called_once()  # halt on exhausted retries


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.merge_conflict_retry.merge_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_handle_worktree_merge_conflict_cleanup_retry_succeeds(
    mock_check_ready,
    mock_merge_worktree,
    mock_invoke_conflict_cleanup,
    mock_retry_merge_worktree,
    mock_add_manifest,
    mock_remove_manifest,
    mock_get_unmerged_files,
    mock_is_merge_in_progress,
    mock_abort_merge,
) -> None:
    """Ensure merge-conflict path retries and cleans manifest on success."""
    mock_check_ready.return_value = (True, "")
    mock_merge_worktree.return_value = MergeResult(success=False)
    mock_retry_merge_worktree.return_value = MergeResult(success=True)
    mock_invoke_conflict_cleanup.return_value = (True, None)
    mock_get_unmerged_files.return_value = ["conflict.txt"]
    mock_is_merge_in_progress.side_effect = [True, True]
    mock_abort_merge.return_value = (True, "")

    agent_item = _make_agent_item()
    success, cleaned = handle_worktree_merge(_make_merge_context(), agent_stats=None)

    assert success is True
    assert cleaned is True
    mock_merge_worktree.assert_called_once()
    mock_retry_merge_worktree.assert_called_once()
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
    mock_merge_worktree.return_value = MergeResult(success=False, unmerged_files=["conflict.txt"])
    mock_invoke_conflict_cleanup.return_value = (False, None)
    mock_is_merge_in_progress.return_value = True
    mock_abort_merge.return_value = (True, "")

    success, cleaned = handle_worktree_merge(_make_merge_context(), agent_stats=None)

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
    mock_merge.return_value = MergeResult(success=True)

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    success, cleaned = perform_worktree_merge(ctx)
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

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    success, cleaned = perform_worktree_merge(ctx)
    assert success is False
    assert cleaned is False
    mock_add.assert_called_once()


@patch("pokepoke.utils.shutdown.request_shutdown")
@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_abort_merge_failure_halts_orchestrator(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging, mock_abort, mock_shutdown,
) -> None:
    """When abort_merge fails, orchestrator must halt (PokePoke-jixa6).

    If abort_merge() fails the main repo is stuck in merge-in-progress state.
    Returning (False, False) alone would release the merge lock and let other
    agents operate on a dirty repo, so we must request_shutdown() instead.
    """
    mock_check.return_value = (True, "")
    mock_merge.return_value = MergeResult(success=False, unmerged_files=["file.py"])
    mock_is_merging.return_value = True
    mock_get_unmerged.return_value = ["file.py"]
    mock_conflict_cleanup.return_value = (True, None)
    mock_abort.return_value = (False, "Cannot abort")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    success, cleaned = perform_worktree_merge(ctx)
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()
    assert mock_merge.call_count == 1
    # Cleanup must NOT run — repo is stuck, lock must stay held
    mock_conflict_cleanup.assert_not_called()
    mock_shutdown.assert_called_once()


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
    """Conflict merge returns out-of-lock cleanup signal after abort."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = MergeResult(success=False, unmerged_files=["file.py"])
    mock_is_merging.return_value = True
    mock_get_unmerged.return_value = ["file.py"]
    mock_abort.return_value = (True, "")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    result = perform_worktree_merge(ctx)
    assert isinstance(result, _ConflictResolutionNeeded)
    assert result.unmerged_files == ["file.py"]
    mock_abort.assert_called_once()
    mock_conflict_cleanup.assert_not_called()
    mock_remove.assert_not_called()


@patch("pokepoke.utils.shutdown.request_shutdown")
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
    mock_get_unmerged, mock_is_merging, mock_abort, mock_shutdown,
) -> None:
    """Abort failure while preparing out-of-lock cleanup halts the orchestrator."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = MergeResult(success=False, unmerged_files=["f.py"])
    mock_is_merging.return_value = True
    mock_get_unmerged.return_value = ["f.py"]
    mock_abort.return_value = (False, "cannot abort")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    success, cleaned = perform_worktree_merge(ctx)  # type: ignore[misc]
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()
    mock_conflict_cleanup.assert_not_called()
    mock_shutdown.assert_called_once()


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
    """Abort still runs before out-of-lock cleanup when merge reported conflict files."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = MergeResult(success=False, unmerged_files=["file.py"])
    mock_is_merging.return_value = False
    mock_abort.return_value = (True, "")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    result = perform_worktree_merge(ctx)
    assert isinstance(result, _ConflictResolutionNeeded)
    mock_abort.assert_called_once()
    mock_conflict_cleanup.assert_not_called()


@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_conflict_details_in_cleanup_prompt(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_abort, mock_get_unmerged, mock_is_merging,
) -> None:
    """Verify conflict_details contains full file list for out-of-lock cleanup."""
    mock_check.return_value = (True, "")
    files = ["src/a.py", "src/b.py", "tests/c.py"]
    mock_merge.return_value = MergeResult(success=False, unmerged_files=files)
    mock_is_merging.return_value = True
    mock_get_unmerged.return_value = files
    mock_abort.return_value = (True, "")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    result = perform_worktree_merge(ctx)
    assert isinstance(result, _ConflictResolutionNeeded)
    assert "Conflicted Files" in result.conflict_details
    assert "src/a.py" in result.conflict_details
    assert result.unmerged_files == files


@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_handles_many_conflict_files(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add, mock_remove,
    mock_abort, mock_get_unmerged, mock_is_merging,
) -> None:
    """15+ files should all be included in out-of-lock cleanup payload."""
    mock_check.return_value = (True, "")
    many_files = [f"src/module{i}.py" for i in range(15)]
    mock_merge.return_value = MergeResult(success=False, unmerged_files=many_files)
    mock_is_merging.return_value = True
    mock_get_unmerged.return_value = many_files
    mock_abort.return_value = (True, "")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    result = perform_worktree_merge(ctx)
    assert isinstance(result, _ConflictResolutionNeeded)
    assert len(result.unmerged_files) == 15


@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_fetches_fresh_unmerged_when_not_merging(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add,
    mock_abort, mock_get_unmerged, mock_is_merging,
) -> None:
    """get_unmerged_files called when merge fails without merge-in-progress."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = MergeResult(success=False)
    mock_is_merging.return_value = False
    mock_get_unmerged.return_value = ["stale.py"]
    mock_abort.return_value = (True, "")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    result = perform_worktree_merge(ctx)
    assert isinstance(result, _ConflictResolutionNeeded)
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
    mock_merge.return_value = MergeResult(success=True)

    # Create a real directory that simulates a worktree not cleaned up
    worktree_dir = tmp_path / "task-item-1"
    worktree_dir.mkdir()

    ctx = _make_merge_context(agent_id="item-1", worktree_path=worktree_dir, repo_root=tmp_path)
    success, cleaned = perform_worktree_merge(ctx)
    assert success is True
    assert cleaned is False
    mock_add.assert_called_once()
    assert "persists" in mock_add.call_args[0][2].lower()


@patch("pokepoke.utils.shutdown.request_shutdown")
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
    mock_get_unmerged, mock_is_merging, mock_abort, mock_shutdown,
) -> None:
    """When abort_merge fails, halt — cleanup agent and retry must not run."""
    mock_check.return_value = (True, "")
    mock_merge.side_effect = [MergeResult(success=False, unmerged_files=["f.py"]), MergeResult(success=False, unmerged_files=["f.py"])]
    mock_is_merging.side_effect = [True, False, True]
    mock_get_unmerged.return_value = ["f.py"]
    mock_conflict_cleanup.return_value = (True, None)
    mock_abort.return_value = (False, "Cannot abort: lock held")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    success, cleaned = perform_worktree_merge(ctx)
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()
    mock_conflict_cleanup.assert_not_called()
    mock_shutdown.assert_called_once()


@patch("pokepoke.utils.shutdown.request_shutdown")
@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_cleanup_failure_abort_failure_logged(
    mock_check, mock_merge, mock_conflict_cleanup, mock_add,
    mock_is_merging, mock_abort, mock_shutdown,
) -> None:
    """When abort_merge fails, orchestrator halts before the cleanup agent runs."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = MergeResult(success=False, unmerged_files=["file.py"])
    mock_is_merging.side_effect = [True, True]
    mock_conflict_cleanup.return_value = (False, None)
    mock_abort.return_value = (False, "Cannot abort")

    ctx = _make_merge_context(agent_id="item-1", worktree_path=Path("C:/wt"), repo_root=Path("C:/repo"))
    success, cleaned = perform_worktree_merge(ctx)
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()
    # Abort precedes cleanup — cleanup agent must not run when abort fails.
    mock_conflict_cleanup.assert_not_called()
    mock_shutdown.assert_called_once()


@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
@patch("pokepoke.git.merge_conflict.get_unmerged_files")
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.merge_conflict_retry.merge_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_perform_retry_merge_worktree_persists(
    mock_check, mock_merge, mock_conflict_cleanup, mock_retry_merge, mock_add, mock_remove,
    mock_get_unmerged, mock_is_merging, mock_abort, tmp_path,
) -> None:
    """Retry merge succeeds via handle path but worktree directory persists — cleaned=False."""
    mock_check.return_value = (True, "")
    mock_merge.return_value = MergeResult(success=False, unmerged_files=["file.py"])
    mock_retry_merge.return_value = MergeResult(success=True)
    mock_is_merging.side_effect = [True, False]
    mock_get_unmerged.return_value = ["file.py"]
    mock_conflict_cleanup.return_value = (True, None)
    mock_abort.return_value = (True, "")

    worktree_dir = tmp_path / "task-item-1"
    worktree_dir.mkdir()

    ctx = _make_merge_context(agent_id="item-1", worktree_path=worktree_dir, repo_root=tmp_path)
    success, cleaned = handle_worktree_merge(ctx)
    assert success is True
    assert cleaned is False
    # Should track in manifest since worktree persists
    mock_add.assert_called()
    # remove_from_manifest still called (from conflict tracking), then re-added for persistence
    mock_remove.assert_called_once_with("item-1")


@patch("pokepoke.worktrees.merge_conflict_retry.merge_worktree")
def test_retry_merge_after_cleanup_halt_required_requests_shutdown(mock_merge: Mock) -> None:
    """halt_required in retry flow should return failure and request shutdown."""
    mock_merge.return_value = MergeResult(success=False, halt_required=True)
    tracker = get_merge_step_tracker()
    tracker.begin_run("item-1", "item-1")
    with patch("pokepoke.utils.shutdown.request_shutdown") as mock_shutdown:
        success, cleaned = retry_merge_after_cleanup(_make_merge_context(agent_id="item-1"), tracker)
    assert success is False
    assert cleaned is False
    mock_shutdown.assert_called_once()


@patch("pokepoke.worktrees.merge_conflict_retry.merge_worktree")
@patch("pokepoke.git.merge_conflict.abort_merge")
@patch("pokepoke.git.merge_conflict.is_merge_in_progress")
def test_retry_merge_after_cleanup_failed_merge_aborts(
    mock_is_merging: Mock,
    mock_abort: Mock,
    mock_merge: Mock,
) -> None:
    """Failed retry merge while merge is in progress should abort and fail."""
    mock_merge.return_value = MergeResult(success=False)
    mock_is_merging.return_value = True
    mock_abort.return_value = (True, "")
    tracker = get_merge_step_tracker()
    tracker.begin_run("item-1", "item-1")
    success, cleaned = retry_merge_after_cleanup(_make_merge_context(agent_id="item-1"), tracker)
    assert success is False
    assert cleaned is False
    mock_abort.assert_called_once()
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

        success, cleaned = handle_worktree_merge(_make_merge_context(agent_id="test", worktree_path=Path("C:/worktrees/task-test")), agent_stats=None)

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

        success, cleaned = handle_worktree_merge(_make_merge_context(agent_id="test", worktree_path=Path("C:/worktrees/task-test")), agent_stats=None)

        assert success is False
        assert cleaned is False
        mock_add.assert_called_once()
        assert "unexpected disk error" in mock_add.call_args[0][2].lower()


# ---------------------------------------------------------------------------
# Regression: cleanup agent must target main repo, not worktree
# ---------------------------------------------------------------------------


@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_cleanup_agent")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_cleanup_agent_receives_main_repo_cwd(
    mock_check_ready,
    mock_add_manifest,
    mock_invoke_cleanup,
    mock_merge_worktree,
    mock_remove_from_manifest,
) -> None:
    """Cleanup agent must be invoked with the main repo path, not the worktree.

    Regression test for a bug where invoke_cleanup_agent was called without cwd,
    causing the cleanup agent to run in the worktree (where everything was clean)
    instead of the main repo (where untracked files blocked the merge).
    """
    mock_check_ready.side_effect = [(False, "untracked files"), (True, "")]
    mock_invoke_cleanup.return_value = (True, None)
    mock_merge_worktree.return_value = MergeResult(success=True)

    repo_path = "C:/my-repo"
    ctx = _make_merge_context(repo_path=repo_path)
    handle_worktree_merge(ctx, agent_stats=None)

    mock_invoke_cleanup.assert_called_once()
    call_kwargs = mock_invoke_cleanup.call_args
    assert call_kwargs[1].get("cwd") == repo_path, (
        f"invoke_cleanup_agent must receive cwd={repo_path!r}, got {call_kwargs}"
    )


@patch("pokepoke.git.merge_conflict.abort_merge", return_value=(True, ""))
@patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
@patch("pokepoke.git.merge_conflict.get_unmerged_files", return_value=["f.py"])
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_merge_conflict_cleanup_receives_worktree_cwd(
    mock_check_ready,
    mock_merge_worktree,
    mock_invoke_conflict_cleanup,
    mock_add_manifest,
    mock_remove_manifest,
    _mock_get_unmerged,
    _mock_is_merging,
    _mock_abort,
) -> None:
    """Merge-conflict cleanup agent must target the isolated worktree, NOT the main repo.

    Regression test for PokePoke-jixa6: once the merge lock is released, the
    cleanup agent must only touch the feature branch in its worktree so other
    agents can merge to main in parallel without interference. Passing
    cwd=repo_path would cause the agent to operate on the shared main repo,
    which races with concurrent merges.
    """
    mock_check_ready.return_value = (True, "")
    mock_merge_worktree.side_effect = [
        MergeResult(success=False, unmerged_files=["f.py"]),
        MergeResult(success=True),
    ]
    mock_invoke_conflict_cleanup.return_value = (True, None)

    repo_path = "C:/my-repo"
    worktree_path = Path("C:/my-repo/worktrees/task-item-1")
    ctx = _make_merge_context(repo_path=repo_path, worktree_path=worktree_path)
    handle_worktree_merge(ctx, agent_stats=None)

    mock_invoke_conflict_cleanup.assert_called_once()
    call_kwargs = mock_invoke_conflict_cleanup.call_args
    assert call_kwargs[1].get("cwd") == str(worktree_path), (
        f"invoke_merge_conflict_cleanup_agent must receive cwd={str(worktree_path)!r} "
        f"(isolated worktree), got {call_kwargs}"
    )
    assert call_kwargs[1].get("cwd") != repo_path, (
        "Cleanup agent must not run in the main repo while merge lock is released"
    )


# ---------------------------------------------------------------------------
# item_logger is forwarded to cleanup agents for log capture
# ---------------------------------------------------------------------------


@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_cleanup_agent")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_cleanup_agent_receives_item_logger(
    mock_check_ready,
    mock_add_manifest,
    mock_invoke_cleanup,
    mock_merge_worktree,
    mock_remove_from_manifest,
) -> None:
    """item_logger from WorktreeMergeContext must be forwarded to cleanup agent."""
    mock_check_ready.side_effect = [(False, "dirty"), (True, "")]
    mock_invoke_cleanup.return_value = (True, None)
    mock_merge_worktree.return_value = MergeResult(success=True)

    sentinel_logger = object()  # stand-in for an ItemLogger
    ctx = _make_merge_context()
    ctx.item_logger = sentinel_logger  # type: ignore[assignment]
    handle_worktree_merge(ctx, agent_stats=None)

    mock_invoke_cleanup.assert_called_once()
    assert mock_invoke_cleanup.call_args[1].get("item_logger") is sentinel_logger


@patch("pokepoke.git.merge_conflict.abort_merge", return_value=(True, ""))
@patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
@patch("pokepoke.git.merge_conflict.get_unmerged_files", return_value=["f.py"])
@patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
@patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
@patch("pokepoke.worktrees.worktree_merge_handler.invoke_merge_conflict_cleanup_agent")
@patch("pokepoke.worktrees.worktree_merge_handler.merge_worktree")
@patch("pokepoke.git.git_operations.check_main_repo_ready_for_merge")
def test_merge_conflict_cleanup_receives_item_logger(
    mock_check_ready,
    mock_merge_worktree,
    mock_invoke_conflict_cleanup,
    mock_add_manifest,
    mock_remove_manifest,
    _mock_get_unmerged,
    _mock_is_merging,
    _mock_abort,
) -> None:
    """item_logger must be forwarded to merge conflict cleanup agent."""
    mock_check_ready.return_value = (True, "")
    mock_merge_worktree.side_effect = [
        MergeResult(success=False, unmerged_files=["f.py"]),
        MergeResult(success=True),
    ]
    mock_invoke_conflict_cleanup.return_value = (True, None)

    sentinel_logger = object()
    ctx = _make_merge_context()
    ctx.item_logger = sentinel_logger  # type: ignore[assignment]
    handle_worktree_merge(ctx, agent_stats=None)

    mock_invoke_conflict_cleanup.assert_called_once()
    assert mock_invoke_conflict_cleanup.call_args[1].get("item_logger") is sentinel_logger
