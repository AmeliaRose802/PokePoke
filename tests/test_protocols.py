"""Tests for Protocol interfaces and Default implementations."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from pokepoke.protocols import (
    DefaultBeadsClient,
    DefaultGitClient,
)
from pokepoke.types import BeadsStats, BeadsWorkItem

# ---------------------------------------------------------------------------
# DefaultGitClient
# ---------------------------------------------------------------------------

class TestDefaultGitClient:
    """Verify DefaultGitClient delegates to module-level git helpers."""

    def test_run_git_delegates(self) -> None:
        client = DefaultGitClient()
        expected = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("pokepoke.git.git_helpers.run_git", return_value=expected) as mock:
            result = client.run_git(["status"], timeout=10, cwd="/tmp", check=False)
        mock.assert_called_once_with(["status"], timeout=10, cwd="/tmp", check=False)
        assert result is expected

    def test_verify_branch_pushed_delegates(self) -> None:
        client = DefaultGitClient()
        with patch("pokepoke.git.git_helpers.verify_branch_pushed", return_value=True) as mock:
            assert client.verify_branch_pushed("main") is True
        mock.assert_called_once_with("main")

    def test_list_worktrees_delegates(self) -> None:
        client = DefaultGitClient()
        expected = [{"worktree": "/path", "branch": "main"}]
        with patch("pokepoke.git.git_helpers.list_worktrees", return_value=expected) as mock:
            result = client.list_worktrees(cwd="/repo")
        mock.assert_called_once_with(cwd="/repo")
        assert result == expected


# ---------------------------------------------------------------------------
# DefaultBeadsClient
# ---------------------------------------------------------------------------

class TestDefaultBeadsClient:
    """Verify DefaultBeadsClient delegates to module-level beads functions."""

    def _make_item(self, item_id: str = "test-1") -> BeadsWorkItem:
        return BeadsWorkItem(
            id=item_id, title="Test", status="open", priority=1, issue_type="task",
        )

    def test_get_ready_work_items_delegates(self) -> None:
        client = DefaultBeadsClient()
        items = [self._make_item()]
        with patch("pokepoke.beads.beads_query.get_ready_work_items", return_value=items) as mock:
            result = client.get_ready_work_items()
        mock.assert_called_once()
        assert result == items

    def test_assign_and_sync_item_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=True) as mock:
            result = client.assign_and_sync_item("item-1", agent_name="agent")
        mock.assert_called_once_with("item-1", agent_name="agent")
        assert result is True

    def test_close_item_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.close_item", return_value=True) as mock:
            result = client.close_item("item-1", "done")
        mock.assert_called_once_with("item-1", message="done")
        assert result is True

    def test_add_comment_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True) as mock:
            result = client.add_comment("item-1", "hello")
        mock.assert_called_once_with("item-1", comment="hello")
        assert result is True

    def test_unassign_item_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.unassign_item", return_value=True) as mock:
            result = client.unassign_item("item-1")
        mock.assert_called_once_with("item-1")
        assert result is True

    def test_unassign_with_retry_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True) as mock:
            result = client.unassign_with_retry("item-1")
        mock.assert_called_once_with("item-1")
        assert result is True

    def test_is_item_claimable_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.is_item_claimable", return_value=True) as mock:
            result = client.is_item_claimable("item-1")
        mock.assert_called_once_with("item-1")
        assert result is True

    def test_select_next_hierarchical_item_delegates(self) -> None:
        client = DefaultBeadsClient()
        items = [self._make_item()]
        with patch("pokepoke.beads.beads_management.select_next_hierarchical_item", return_value=items[0]) as mock:
            result = client.select_next_hierarchical_item(items)
        mock.assert_called_once_with(items)
        assert result is items[0]

    def test_get_beads_stats_delegates(self) -> None:
        client = DefaultBeadsClient()
        stats = BeadsStats()
        with patch("pokepoke.beads.beads_query.get_beads_stats", return_value=stats) as mock:
            result = client.get_beads_stats()
        mock.assert_called_once()
        assert result is stats

    def test_get_issue_dependencies_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_query.get_issue_dependencies", return_value=None) as mock:
            result = client.get_issue_dependencies("item-1")
        mock.assert_called_once_with("item-1")
        assert result is None

    def test_increment_total_attempts_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.increment_total_attempts", return_value=True) as mock:
            result = client.increment_total_attempts("item-1")
        mock.assert_called_once_with("item-1")
        assert result is True

    def test_fail_task_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.fail_task", return_value=True) as mock:
            result = client.fail_task("item-1", "agent crashed", agent_type="gate")
        mock.assert_called_once_with("item-1", "agent crashed", agent_type="gate")
        assert result is True

    def test_fail_task_delegates_default_agent_type(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_management.fail_task", return_value=False) as mock:
            result = client.fail_task("item-1", "timeout")
        mock.assert_called_once_with("item-1", "timeout", agent_type="work")
        assert result is False

    def test_retry_failed_unassigns_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_recovery.retry_failed_unassigns", return_value=2) as mock:
            result = client.retry_failed_unassigns()
        mock.assert_called_once()
        assert result == 2

    def test_get_failed_unassign_count_delegates(self) -> None:
        client = DefaultBeadsClient()
        with patch("pokepoke.beads.beads_recovery.get_failed_unassign_count", return_value=3) as mock:
            result = client.get_failed_unassign_count()
        mock.assert_called_once()
        assert result == 3

    def test_run_bd_sync_with_retry_delegates(self) -> None:
        client = DefaultBeadsClient()
        expected = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("pokepoke.beads.beads_management.run_bd_sync_with_retry", return_value=expected) as mock:
            result = client.run_bd_sync_with_retry(max_attempts=2, base_delay=1.0, timeout=30)
        mock.assert_called_once_with(max_attempts=2, base_delay=1.0, timeout=30)
        assert result is expected
