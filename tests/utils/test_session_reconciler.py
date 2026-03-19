"""Tests for pokepoke.stats.session_reconciler."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.stats.session_journal import (
    SessionJournal,
    SessionPhase,
    write_journal,
)
from pokepoke.stats.session_reconciler import (
    _delete_branch,
    _reconcile_journal,
    _remove_worktree,
    _session_age_seconds,
    _should_unassign,
    _unassign_item,
    run,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sessions_dir(tmp_path: Path) -> Path:
    """Create a temporary sessions directory."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d


def _write_test_journal(
    sessions_dir: Path,
    item_id: str = "TEST-001",
    branch: str = "task/TEST-001",
    worktree_path: str = "/fake/worktree",
    agent_name: str = "Janitor",
    phase: SessionPhase = SessionPhase.ACTIVE,
    pid: int = 99999,
    started_at: str = "2020-01-01T00:00:00+00:00",
) -> SessionJournal:
    """Write a test journal and return the corresponding SessionJournal."""
    write_journal(
        item_id=item_id,
        branch=branch,
        worktree_path=worktree_path,
        agent_name=agent_name,
        phase=phase,
        pid=pid,
        started_at=started_at,
        sessions_dir=sessions_dir,
    )
    return SessionJournal(
        item_id=item_id,
        branch=branch,
        worktree_path=worktree_path,
        agent_name=agent_name,
        pid=pid,
        started_at=started_at,
        phase=phase.value,
    )


# ---------------------------------------------------------------------------
# Tests: CLOSED journal
# ---------------------------------------------------------------------------


class TestClosedJournal:
    def test_closed_journal_deleted_no_side_effects(self, sessions_dir: Path) -> None:
        """CLOSED journal should be deleted with no cleanup actions."""
        journal = _write_test_journal(sessions_dir, phase=SessionPhase.CLOSED)
        journal_path = sessions_dir / f"{journal.item_id}.json"
        assert journal_path.exists()

        with (
            patch("pokepoke.stats.session_reconciler._remove_worktree") as mock_rm,
            patch("pokepoke.stats.session_reconciler._delete_branch") as mock_br,
            patch("pokepoke.stats.session_reconciler._should_unassign") as mock_ua,
        ):
            _reconcile_journal(journal, session_timeout=9999, sessions_dir=sessions_dir)

        assert not journal_path.exists()
        mock_rm.assert_not_called()
        mock_br.assert_not_called()
        mock_ua.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: alive PID within timeout
# ---------------------------------------------------------------------------


class TestAlivePidWithinTimeout:
    def test_alive_pid_young_session_skipped(self, sessions_dir: Path) -> None:
        """Alive PID + age < SESSION_TIMEOUT should be skipped entirely."""
        journal = _write_test_journal(
            sessions_dir,
            pid=os.getpid(),  # current process is alive
            started_at="2099-01-01T00:00:00+00:00",  # far in the future → age < 0
        )
        journal_path = sessions_dir / f"{journal.item_id}.json"

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=True),
            patch("pokepoke.stats.session_reconciler.delete_journal") as mock_delete,
            patch("pokepoke.stats.session_reconciler._remove_worktree") as mock_rm,
            patch("pokepoke.stats.session_reconciler._delete_branch") as mock_br,
            patch("pokepoke.stats.session_reconciler._should_unassign") as mock_ua,
        ):
            _reconcile_journal(journal, session_timeout=999999, sessions_dir=sessions_dir)

        # Journal should still exist (skipped, not cleaned)
        assert journal_path.exists()
        mock_rm.assert_not_called()
        mock_br.assert_not_called()
        mock_ua.assert_not_called()
        mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: dead PID cleanup
# ---------------------------------------------------------------------------


class TestDeadPidCleanup:
    def test_dead_pid_full_cleanup(self, sessions_dir: Path, tmp_path: Path) -> None:
        """Dead PID + worktree exists: worktree removed, branch deleted, item unassigned, journal deleted."""
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        journal = _write_test_journal(
            sessions_dir,
            worktree_path=str(wt_path),
            pid=1,  # PID 1 unlikely to be our process
            started_at="2020-01-01T00:00:00+00:00",
        )
        journal_path = sessions_dir / f"{journal.item_id}.json"

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=False),
            patch("pokepoke.stats.session_reconciler._remove_worktree", return_value=True) as mock_rm,
            patch("pokepoke.stats.session_reconciler._delete_branch", return_value=True) as mock_br,
            patch("pokepoke.stats.session_reconciler._should_unassign", return_value=True),
            patch("pokepoke.stats.session_reconciler._unassign_item", return_value=True) as mock_ua,
        ):
            _reconcile_journal(journal, session_timeout=1, sessions_dir=sessions_dir)

        mock_rm.assert_called_once_with(str(wt_path))
        mock_br.assert_called_once_with(journal.branch)
        mock_ua.assert_called_once_with(journal.item_id)
        assert not journal_path.exists()

    def test_dead_pid_no_worktree_no_branch_only_journal_deleted(
        self, sessions_dir: Path
    ) -> None:
        """Dead PID + worktree absent + branch absent + item open: only journal deleted."""
        journal = _write_test_journal(
            sessions_dir,
            worktree_path="/nonexistent/path",
            pid=1,
            started_at="2020-01-01T00:00:00+00:00",
        )
        journal_path = sessions_dir / f"{journal.item_id}.json"

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=False),
            patch("pokepoke.stats.session_reconciler._delete_branch", return_value=True) as mock_br,
            patch("pokepoke.stats.session_reconciler._should_unassign", return_value=False),
        ):
            _reconcile_journal(journal, session_timeout=1, sessions_dir=sessions_dir)

        mock_br.assert_called_once()
        assert not journal_path.exists()


# ---------------------------------------------------------------------------
# Tests: cleanup failures leave journal
# ---------------------------------------------------------------------------


class TestCleanupFailures:
    def test_remove_worktree_fails_journal_kept(
        self, sessions_dir: Path, tmp_path: Path
    ) -> None:
        """Dead PID + remove_worktree fails: ERROR logged, journal left for next cycle."""
        wt_path = tmp_path / "worktree"
        wt_path.mkdir()

        journal = _write_test_journal(
            sessions_dir,
            worktree_path=str(wt_path),
            pid=1,
            started_at="2020-01-01T00:00:00+00:00",
        )
        journal_path = sessions_dir / f"{journal.item_id}.json"

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=False),
            patch("pokepoke.stats.session_reconciler._remove_worktree", return_value=False),
            patch("pokepoke.stats.session_reconciler._delete_branch", return_value=True),
            patch("pokepoke.stats.session_reconciler._should_unassign", return_value=False),
        ):
            _reconcile_journal(journal, session_timeout=1, sessions_dir=sessions_dir)

        # Journal should remain because worktree removal failed
        assert journal_path.exists()

    def test_unassign_fails_journal_kept(self, sessions_dir: Path) -> None:
        """Dead PID + unassign fails: ERROR logged, journal left for next cycle."""
        journal = _write_test_journal(
            sessions_dir,
            worktree_path="/nonexistent",
            pid=1,
            started_at="2020-01-01T00:00:00+00:00",
        )
        journal_path = sessions_dir / f"{journal.item_id}.json"

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=False),
            patch("pokepoke.stats.session_reconciler._delete_branch", return_value=True),
            patch("pokepoke.stats.session_reconciler._should_unassign", return_value=True),
            patch("pokepoke.stats.session_reconciler._unassign_item", return_value=False),
        ):
            _reconcile_journal(journal, session_timeout=1, sessions_dir=sessions_dir)

        assert journal_path.exists()


# ---------------------------------------------------------------------------
# Tests: ABANDONED phase
# ---------------------------------------------------------------------------


class TestAbandonedPhase:
    def test_abandoned_journal_picked_up(self, sessions_dir: Path) -> None:
        """ABANDONED journal from prior failed unwind should be reconciled."""
        journal = _write_test_journal(
            sessions_dir,
            phase=SessionPhase.ABANDONED,
            worktree_path="/nonexistent",
            pid=1,
            started_at="2020-01-01T00:00:00+00:00",
        )
        journal_path = sessions_dir / f"{journal.item_id}.json"

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=False),
            patch("pokepoke.stats.session_reconciler._delete_branch", return_value=True),
            patch("pokepoke.stats.session_reconciler._should_unassign", return_value=False),
        ):
            _reconcile_journal(journal, session_timeout=1, sessions_dir=sessions_dir)

        assert not journal_path.exists()


# ---------------------------------------------------------------------------
# Tests: SESSION_TIMEOUT configuration
# ---------------------------------------------------------------------------


class TestSessionTimeout:
    def test_timeout_uses_config(self) -> None:
        """SESSION_TIMEOUT should be configurable via config.timeout_hours * 2."""
        from pokepoke.stats.session_reconciler import _get_session_timeout_seconds

        # Default workflow timeout_hours is 0.5, so timeout = 0.5 * 2 * 3600 = 3600
        timeout = _get_session_timeout_seconds()
        assert timeout == 0.5 * 2 * 3600


# ---------------------------------------------------------------------------
# Tests: run() integration
# ---------------------------------------------------------------------------


class TestRun:
    def test_run_called_from_maintenance(self) -> None:
        """reconciler.run() should be callable from the maintenance scheduler."""
        # Just verify the function signature and return type
        result = run(sessions_dir=Path("/nonexistent"))
        assert result == 0

    def test_run_processes_multiple_journals(self, sessions_dir: Path) -> None:
        """run() processes all journals in the sessions directory."""
        # Write a CLOSED journal (should be deleted) and an active one (dead PID)
        _write_test_journal(
            sessions_dir, item_id="CLOSED-001", phase=SessionPhase.CLOSED
        )
        _write_test_journal(
            sessions_dir,
            item_id="DEAD-001",
            worktree_path="/nonexistent",
            pid=1,
            started_at="2020-01-01T00:00:00+00:00",
        )

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=False),
            patch("pokepoke.stats.session_reconciler._delete_branch", return_value=True),
            patch("pokepoke.stats.session_reconciler._should_unassign", return_value=False),
        ):
            result = run(sessions_dir=sessions_dir)

        assert result == 2
        assert not (sessions_dir / "CLOSED-001.json").exists()
        assert not (sessions_dir / "DEAD-001.json").exists()

    def test_run_empty_dir_returns_zero(self, sessions_dir: Path) -> None:
        """run() with no journals returns 0."""
        assert run(sessions_dir=sessions_dir) == 0


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_session_age_seconds_valid(self) -> None:
        """_session_age_seconds returns positive value for old timestamp."""
        journal = SessionJournal(
            item_id="X", branch="b", worktree_path="/w",
            agent_name="a", pid=1,
            started_at="2020-01-01T00:00:00+00:00",
            phase="ACTIVE",
        )
        assert _session_age_seconds(journal) > 0

    def test_session_age_seconds_invalid_returns_inf(self) -> None:
        """_session_age_seconds returns inf for unparseable timestamp."""
        journal = SessionJournal(
            item_id="X", branch="b", worktree_path="/w",
            agent_name="a", pid=1,
            started_at="not-a-timestamp",
            phase="ACTIVE",
        )
        assert _session_age_seconds(journal) == float("inf")

    def test_should_unassign_true(self) -> None:
        """_should_unassign returns True when item is in_progress and assigned to agent."""
        mock_result = MagicMock()
        mock_result.stdout = json.dumps([{
            "status": "in_progress",
            "assignee": "test-agent",
        }])

        with patch("subprocess.run", return_value=mock_result):
            assert _should_unassign("ITEM-1", "test-agent") is True

    def test_should_unassign_false_wrong_assignee(self) -> None:
        """_should_unassign returns False when assigned to different agent."""
        mock_result = MagicMock()
        mock_result.stdout = json.dumps([{
            "status": "in_progress",
            "assignee": "other-agent",
        }])

        with patch("subprocess.run", return_value=mock_result):
            assert _should_unassign("ITEM-1", "test-agent") is False

    def test_should_unassign_false_not_in_progress(self) -> None:
        """_should_unassign returns False when item is not in_progress."""
        mock_result = MagicMock()
        mock_result.stdout = json.dumps([{
            "status": "open",
            "assignee": "test-agent",
        }])

        with patch("subprocess.run", return_value=mock_result):
            assert _should_unassign("ITEM-1", "test-agent") is False

    def test_should_unassign_handles_exception(self) -> None:
        """_should_unassign returns False on subprocess failure."""
        with patch("subprocess.run", side_effect=Exception("boom")):
            assert _should_unassign("ITEM-1", "test-agent") is False

    def test_should_unassign_empty_items(self) -> None:
        """_should_unassign returns False when bd show returns empty list."""
        mock_result = MagicMock()
        mock_result.stdout = "[]"
        with patch("subprocess.run", return_value=mock_result):
            assert _should_unassign("ITEM-1", "test-agent") is False

    def test_session_age_naive_timestamp(self) -> None:
        """_session_age_seconds handles naive (no timezone) timestamps."""
        journal = SessionJournal(
            item_id="X", branch="b", worktree_path="/w",
            agent_name="a", pid=1,
            started_at="2020-01-01T00:00:00",
            phase="ACTIVE",
        )
        age = _session_age_seconds(journal)
        assert age > 0

    def test_remove_worktree_nonexistent_returns_true(self) -> None:
        """_remove_worktree returns True for nonexistent path."""
        assert _remove_worktree("/nonexistent/path/abc123") is True

    def test_remove_worktree_exists_calls_force_remove(self, tmp_path: Path) -> None:
        """_remove_worktree calls force_remove_directory for existing paths."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("pokepoke.stats.session_reconciler.Path.exists", return_value=True),
            patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=True) as mock_frd,
        ):
            result = _remove_worktree(str(wt))
        assert result is True
        mock_frd.assert_called_once()

    def test_remove_worktree_exception_returns_false(self, tmp_path: Path) -> None:
        """_remove_worktree returns False when force_remove_directory raises."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", side_effect=RuntimeError("fail")):
            result = _remove_worktree(str(wt))
        assert result is False

    def test_delete_branch_nonexistent_returns_true(self) -> None:
        """_delete_branch returns True when branch doesn't exist."""
        with patch("pokepoke.git.git_operations.branch_exists", return_value=False):
            assert _delete_branch("task/nonexistent") is True

    def test_delete_branch_exists_success(self) -> None:
        """_delete_branch returns True on successful git branch -D."""
        with (
            patch("pokepoke.git.git_operations.branch_exists", return_value=True),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            assert _delete_branch("task/test") is True

    def test_delete_branch_failure_returns_false(self) -> None:
        """_delete_branch returns False when git branch -D fails."""
        with (
            patch("pokepoke.git.git_operations.branch_exists", return_value=True),
            patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")),
        ):
            assert _delete_branch("task/test") is False

    def test_unassign_item_success(self) -> None:
        """_unassign_item returns True on success."""
        with patch("pokepoke.beads.beads_management.unassign_item", return_value=True):
            assert _unassign_item("ITEM-1") is True

    def test_unassign_item_failure(self) -> None:
        """_unassign_item returns False on exception."""
        with patch("pokepoke.beads.beads_management.unassign_item", side_effect=RuntimeError("fail")):
            assert _unassign_item("ITEM-1") is False

    def test_branch_delete_failure_leaves_journal(self, sessions_dir: Path) -> None:
        """Branch deletion failure should leave journal for next cycle."""
        journal = _write_test_journal(
            sessions_dir,
            worktree_path="/nonexistent",
            pid=1,
            started_at="2020-01-01T00:00:00+00:00",
        )
        journal_path = sessions_dir / f"{journal.item_id}.json"

        with (
            patch("pokepoke.stats.session_reconciler.is_process_running", return_value=False),
            patch("pokepoke.stats.session_reconciler._delete_branch", return_value=False),
            patch("pokepoke.stats.session_reconciler._should_unassign", return_value=False),
        ):
            _reconcile_journal(journal, session_timeout=1, sessions_dir=sessions_dir)

        assert journal_path.exists()
