"""Unit tests for pokepoke.reconciliation module.

Tests the post-session reconciliation logic that detects whether work
for a beads item already landed even when the Copilot CLI session
reported failure.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.reconciliation import (
    default_branch_has_merge_commit,
    is_beads_item_closed,
    is_worktree_cleaned,
    reconcile_completed_item,
)
from pokepoke.types import BeadsWorkItem


def _item(id: str = "TEST-1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=id, title=f"Item {id}", status="ready",
        priority=1, issue_type="task", description="desc",
    )


# ── is_beads_item_closed ──────────────────────────────────────────


class TestIsBeadsItemClosed:
    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_true_when_status_closed(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps([{"id": "X-1", "status": "closed"}]),
        )
        assert is_beads_item_closed("X-1") is True

    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_true_when_status_completed(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps([{"id": "X-1", "status": "Completed"}]),
        )
        assert is_beads_item_closed("X-1") is True

    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_false_when_status_ready(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps([{"id": "X-1", "status": "ready"}]),
        )
        assert is_beads_item_closed("X-1") is False

    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_false_when_empty_list(self, mock_run):
        mock_run.return_value = MagicMock(stdout="[]")
        assert is_beads_item_closed("X-1") is False

    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_false_when_no_status_key(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout=json.dumps([{"id": "X-1"}]),
        )
        assert is_beads_item_closed("X-1") is False

    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_false_on_empty_stdout(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        assert is_beads_item_closed("X-1") is False

    @patch("pokepoke.reconciliation.subprocess.run")
    def test_passes_correct_args(self, mock_run):
        mock_run.return_value = MagicMock(stdout="[]")
        is_beads_item_closed("my-item-42")
        args = mock_run.call_args
        assert args[0][0] == ["bd", "show", "my-item-42", "--json"]


# ── default_branch_has_merge_commit ───────────────────────────────


class TestDefaultBranchHasMergeCommit:
    @patch("pokepoke.reconciliation.get_default_branch", return_value="main")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_true_when_commit_found_on_origin(
        self, mock_run, mock_sanitize, mock_default
    ):
        # First call: git fetch (always succeeds)
        fetch_result = MagicMock()
        # Second call: git log origin/main finds a commit hash
        log_result = MagicMock(stdout="abc123def456\n")
        mock_run.side_effect = [fetch_result, log_result]

        assert default_branch_has_merge_commit("X-1", Path("/repo")) is True

    @patch("pokepoke.reconciliation.get_default_branch", return_value="main")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    @patch("pokepoke.reconciliation.subprocess.run")
    def test_returns_false_when_no_commits_found(
        self, mock_run, mock_sanitize, mock_default
    ):
        fetch_result = MagicMock()
        # Both git log calls return empty output
        empty_log = MagicMock(stdout="")
        mock_run.side_effect = [fetch_result, empty_log, empty_log]

        assert default_branch_has_merge_commit("X-1", Path("/repo")) is False

    @patch("pokepoke.reconciliation.get_default_branch", return_value="main")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    @patch("pokepoke.reconciliation.subprocess.run")
    def test_falls_back_to_local_branch_on_origin_failure(
        self, mock_run, mock_sanitize, mock_default
    ):
        fetch_result = MagicMock()
        # origin/main git log fails
        origin_fail = subprocess.CalledProcessError(1, "git")
        # local main git log succeeds
        local_result = MagicMock(stdout="abc123\n")
        mock_run.side_effect = [fetch_result, origin_fail, local_result]

        assert default_branch_has_merge_commit("X-1", Path("/repo")) is True

    @patch("pokepoke.reconciliation.get_default_branch", return_value="main")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    @patch("pokepoke.reconciliation.subprocess.run")
    def test_fetch_failure_is_non_fatal(
        self, mock_run, mock_sanitize, mock_default
    ):
        # Fetch raises an exception; should be suppressed
        mock_run.side_effect = [
            Exception("network error"),
            MagicMock(stdout="abc123\n"),
        ]
        assert default_branch_has_merge_commit("X-1", Path("/repo")) is True

    @patch("pokepoke.reconciliation.get_default_branch", return_value="main")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    @patch("pokepoke.reconciliation.subprocess.run")
    def test_uses_sanitized_branch_name_in_grep(
        self, mock_run, mock_sanitize, mock_default
    ):
        fetch_result = MagicMock()
        log_result = MagicMock(stdout="abc\n")
        mock_run.side_effect = [fetch_result, log_result]

        default_branch_has_merge_commit("MY-ITEM", Path("/repo"))
        # The git log call should grep for task/MY-ITEM
        log_call_args = mock_run.call_args_list[1][0][0]
        assert "task/MY-ITEM" in log_call_args


# ── is_worktree_cleaned ──────────────────────────────────────────


class TestIsWorktreeCleaned:
    @patch("pokepoke.reconciliation.list_worktrees", return_value=[])
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    def test_returns_true_when_no_worktrees_and_path_absent(
        self, mock_sanitize, mock_list, tmp_path
    ):
        # worktree_path doesn't exist on disk
        wt_path = tmp_path / "worktrees" / "task-X-1"
        assert is_worktree_cleaned("X-1", wt_path) is True

    @patch("pokepoke.reconciliation.list_worktrees", return_value=[])
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    def test_returns_false_when_path_still_exists(
        self, mock_sanitize, mock_list, tmp_path
    ):
        wt_path = tmp_path / "worktrees" / "task-X-1"
        wt_path.mkdir(parents=True)
        assert is_worktree_cleaned("X-1", wt_path) is False

    @patch("pokepoke.reconciliation.list_worktrees")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    def test_returns_false_when_branch_still_in_worktrees(
        self, mock_sanitize, mock_list, tmp_path
    ):
        mock_list.return_value = [
            {"branch": "refs/heads/task/X-1", "path": str(tmp_path / "other")},
        ]
        wt_path = tmp_path / "worktrees" / "task-X-1"
        assert is_worktree_cleaned("X-1", wt_path) is False

    @patch("pokepoke.reconciliation.list_worktrees")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    def test_returns_false_when_path_matches_active_worktree(
        self, mock_sanitize, mock_list, tmp_path
    ):
        wt_path = tmp_path / "worktrees" / "task-X-1"
        wt_path.mkdir(parents=True)
        mock_list.return_value = [
            {"branch": "refs/heads/other-branch", "path": str(wt_path)},
        ]
        assert is_worktree_cleaned("X-1", wt_path) is False

    @patch("pokepoke.reconciliation.list_worktrees", return_value=[])
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    def test_uses_default_path_when_worktree_path_is_none(
        self, mock_sanitize, mock_list, monkeypatch, tmp_path
    ):
        # When worktree_path is None, falls back to cwd / worktrees / task-{id}
        monkeypatch.chdir(tmp_path)
        # default path doesn't exist, so should be True
        assert is_worktree_cleaned("X-1", None) is True

    @patch("pokepoke.reconciliation.list_worktrees")
    @patch("pokepoke.reconciliation.sanitize_branch_name", side_effect=lambda x: x)
    def test_returns_false_when_path_resolve_raises_oserror(
        self, mock_sanitize, mock_list, tmp_path, monkeypatch
    ):
        """OSError during path resolution conservatively assumes worktree exists."""
        wt_path = tmp_path / "worktrees" / "task-X-1"
        bad_path_str = "Z:\\bad\\long\\path\\exceeds\\max"
        mock_list.return_value = [
            {"branch": "refs/heads/other-branch", "path": bad_path_str},
        ]
        _original = type(wt_path).resolve

        def _raise_for_bad(self, strict=False):
            if str(self) == bad_path_str:
                raise OSError("path exceeds MAX_PATH")
            return _original(self, strict=strict)

        monkeypatch.setattr(type(wt_path), "resolve", _raise_for_bad)
        assert is_worktree_cleaned("X-1", wt_path) is False


# ── reconcile_completed_item ─────────────────────────────────────


class TestReconcileCompletedItem:
    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=True)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=True)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=True)
    def test_reconciled_when_all_checks_pass(
        self, mock_closed, mock_commits, mock_wt
    ):
        item = _item()
        reconciled, evidence = reconcile_completed_item(item, Path("/wt"), None)
        assert reconciled is True
        assert evidence == {
            "beads_closed": True,
            "commits_on_default": True,
            "worktree_cleaned": True,
        }

    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=True)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=False)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=True)
    def test_not_reconciled_when_no_merge_commit(
        self, mock_closed, mock_commits, mock_wt
    ):
        """False-positive guard: worktree cleaned + beads closed but no merge commit."""
        item = _item()
        reconciled, evidence = reconcile_completed_item(item, Path("/wt"), None)
        assert reconciled is False
        assert evidence["commits_on_default"] is False

    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=False)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=True)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=True)
    def test_not_reconciled_when_worktree_not_cleaned(
        self, mock_closed, mock_commits, mock_wt
    ):
        item = _item()
        reconciled, evidence = reconcile_completed_item(item, Path("/wt"), None)
        assert reconciled is False
        assert evidence["worktree_cleaned"] is False

    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=True)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=True)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=False)
    def test_not_reconciled_when_beads_not_closed(
        self, mock_closed, mock_commits, mock_wt
    ):
        item = _item()
        reconciled, evidence = reconcile_completed_item(item, Path("/wt"), None)
        assert reconciled is False
        assert evidence["beads_closed"] is False

    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=False)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=False)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=False)
    def test_not_reconciled_when_all_checks_fail(
        self, mock_closed, mock_commits, mock_wt
    ):
        item = _item()
        reconciled, evidence = reconcile_completed_item(item, Path("/wt"), None)
        assert reconciled is False
        assert all(v is False for v in evidence.values())

    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=True)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=True)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=True)
    def test_logs_warning_when_reconciled(
        self, mock_closed, mock_commits, mock_wt
    ):
        run_logger = MagicMock()
        item = _item()
        reconcile_completed_item(item, Path("/wt"), run_logger)
        run_logger.log_orchestrator.assert_called_once()
        call_kwargs = run_logger.log_orchestrator.call_args
        assert call_kwargs[1]["level"] == "WARNING"

    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=False)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=False)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=False)
    def test_logs_info_when_not_reconciled(
        self, mock_closed, mock_commits, mock_wt
    ):
        run_logger = MagicMock()
        item = _item()
        reconcile_completed_item(item, Path("/wt"), run_logger)
        run_logger.log_orchestrator.assert_called_once()
        call_kwargs = run_logger.log_orchestrator.call_args
        assert call_kwargs[1]["level"] == "INFO"

    @patch("pokepoke.reconciliation.is_worktree_cleaned", return_value=True)
    @patch("pokepoke.reconciliation.default_branch_has_merge_commit", return_value=True)
    @patch("pokepoke.reconciliation.is_beads_item_closed", return_value=True)
    def test_works_without_logger(
        self, mock_closed, mock_commits, mock_wt
    ):
        item = _item()
        reconciled, evidence = reconcile_completed_item(item, None, None)
        assert reconciled is True
