"""Comprehensive coverage tests for beads_management.py functions."""

import contextlib
import subprocess
from unittest.mock import MagicMock, patch

from pokepoke.beads.beads_management import (
    _resolve_with_timeout,
    add_comment,
    assign_and_sync_item,
    block_item,
    close_item,
    defer_item,
    fail_task,
    is_item_claimable,
    select_next_hierarchical_item,
    unassign_item,
)
from pokepoke.types_beads import BeadsWorkItem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(**overrides) -> BeadsWorkItem:
    """Create a BeadsWorkItem with sensible defaults."""
    defaults = dict(
        id="item-1",
        title="Test item",
        status="open",
        priority=1,
        issue_type="task",
    )
    defaults.update(overrides)
    return BeadsWorkItem(**defaults)


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(["mock-cmd"], returncode, stdout, stderr)


MODULE = "pokepoke.beads.beads_management"


# ===================================================================
# is_item_claimable
# ===================================================================

class TestIsItemClaimable:
    """Tests for is_item_claimable."""

    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    def test_unassigned_item_returns_true(self, mock_run, mock_parse):
        mock_run.return_value = _completed(stdout='{}')
        mock_parse.return_value = [{"assignee": "", "status": "open"}]
        assert is_item_claimable("item-1") is True

    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    def test_assigned_item_returns_false(self, mock_run, mock_parse):
        mock_run.return_value = _completed(stdout='{}')
        mock_parse.return_value = [{"assignee": "other_agent", "status": "in_progress"}]
        assert is_item_claimable("item-1") is False

    @patch(f"{MODULE}._run_bd")
    def test_subprocess_error_returns_false(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd")
        assert is_item_claimable("item-1") is False

    @patch(f"{MODULE}._run_bd")
    def test_json_parse_error_returns_false(self, mock_run):
        mock_run.return_value = _completed(stdout="not json")
        with patch(f"{MODULE}._parse_beads_json", side_effect=ValueError("bad json")):
            # JSONDecodeError inherits ValueError, but the function catches json.JSONDecodeError
            pass
        # Patch _parse_beads_json to raise json.JSONDecodeError
        import json
        with patch(f"{MODULE}._parse_beads_json",
                   side_effect=json.JSONDecodeError("msg", "doc", 0)):
            assert is_item_claimable("item-1") is False

    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    def test_data_is_none_returns_false(self, mock_run, mock_parse):
        mock_run.return_value = _completed(stdout='')
        mock_parse.return_value = None
        assert is_item_claimable("item-1") is False


# ===================================================================
# assign_and_sync_item
# ===================================================================

class TestAssignAndSyncItem:
    """Tests for assign_and_sync_item."""

    @patch(f"{MODULE}.run_bd_sync_with_retry")
    @patch(f"{MODULE}._rollback_assignment")
    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_success_full_flow(
        self, mock_agent, mock_run, mock_parse, mock_lock,
        mock_rollback, mock_sync,
    ):
        """Check → claim → verify → sync succeeds."""
        mock_lock.return_value = contextlib.nullcontext()
        # First show: unassigned
        # Second (update): succeed
        # Third show (verify): assigned to us
        mock_run.side_effect = [
            _completed(stdout='{}'),  # show
            _completed(),              # update
            _completed(stdout='{}'),  # verify show
        ]
        mock_parse.side_effect = [
            [{"assignee": "", "status": "open"}],     # initial check
            [{"assignee": "pokepoke_test_agent", "status": "in_progress"}],  # verify
        ]
        mock_sync.return_value = _completed()

        result = assign_and_sync_item("item-1")
        assert result is True
        mock_rollback.assert_not_called()

    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_already_assigned_to_another_agent(
        self, mock_agent, mock_run, mock_parse, mock_lock,
    ):
        """Item assigned to a non-pokepoke agent → False."""
        mock_lock.return_value = contextlib.nullcontext()
        mock_run.return_value = _completed(stdout='{}')
        mock_parse.return_value = [{"assignee": "human_dev", "status": "in_progress"}]

        result = assign_and_sync_item("item-1")
        assert result is False

    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_already_assigned_to_self_in_progress_skips_update(
        self, mock_agent, mock_run, mock_parse, mock_lock,
    ):
        """Item already assigned to us and in_progress → True (no update)."""
        mock_lock.return_value = contextlib.nullcontext()
        mock_run.return_value = _completed(stdout='{}')
        mock_parse.return_value = [
            {"assignee": "pokepoke_test_agent", "status": "in_progress"},
        ]

        result = assign_and_sync_item("item-1")
        assert result is True
        # Only one _run_bd call (show), no update call
        assert mock_run.call_count == 1

    @patch(f"{MODULE}.run_bd_sync_with_retry")
    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_reclaim_from_dead_pokepoke_agent(
        self, mock_agent, mock_run, mock_parse, mock_lock, mock_sync,
    ):
        """Orphaned pokepoke_ agent → reclaim succeeds."""
        mock_lock.return_value = contextlib.nullcontext()
        mock_run.side_effect = [
            _completed(stdout='{}'),  # show: assigned to dead agent
            _completed(),              # update
            _completed(stdout='{}'),  # verify
        ]
        mock_parse.side_effect = [
            [{"assignee": "pokepoke_dead_agent", "status": "in_progress"}],
            [{"assignee": "pokepoke_test_agent", "status": "in_progress"}],
        ]
        mock_sync.return_value = _completed()

        result = assign_and_sync_item("item-1")
        assert result is True

    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_lock_busy_timeout_returns_false(self, mock_agent, mock_lock):
        """Timeout on lock acquisition → False."""
        from filelock import Timeout

        mock_lock.side_effect = Timeout("lock")
        result = assign_and_sync_item("item-1")
        assert result is False

    @patch(f"{MODULE}._rollback_assignment")
    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_verify_fails_different_assignee_triggers_rollback(
        self, mock_agent, mock_run, mock_parse, mock_lock, mock_rollback,
    ):
        """Verify shows different assignee → rollback and False."""
        mock_lock.return_value = contextlib.nullcontext()
        mock_run.side_effect = [
            _completed(stdout='{}'),  # show: unassigned
            _completed(),              # update: success
            _completed(stdout='{}'),  # verify show
        ]
        mock_parse.side_effect = [
            [{"assignee": "", "status": "open"}],
            [{"assignee": "sneaky_other_agent", "status": "in_progress"}],
        ]

        result = assign_and_sync_item("item-1")
        assert result is False
        mock_rollback.assert_called_once()

    @patch(f"{MODULE}._rollback_assignment")
    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_verify_returns_none_triggers_rollback(
        self, mock_agent, mock_run, mock_parse, mock_lock, mock_rollback,
    ):
        """Verify parse returns None → rollback and False."""
        mock_lock.return_value = contextlib.nullcontext()
        mock_run.side_effect = [
            _completed(stdout='{}'),  # show: unassigned
            _completed(),              # update
            _completed(stdout=''),    # verify show (empty)
        ]
        mock_parse.side_effect = [
            [{"assignee": "", "status": "open"}],
            None,  # verify parse returns None
        ]

        result = assign_and_sync_item("item-1")
        assert result is False
        mock_rollback.assert_called_once()

    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._parse_beads_json")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_update_subprocess_error_returns_false(
        self, mock_agent, mock_run, mock_parse, mock_lock,
    ):
        """Update command raises CalledProcessError → False."""
        mock_lock.return_value = contextlib.nullcontext()
        mock_run.side_effect = [
            _completed(stdout='{}'),  # show
            subprocess.CalledProcessError(1, "bd", stderr="update failed"),
        ]
        mock_parse.return_value = [{"assignee": "", "status": "open"}]

        result = assign_and_sync_item("item-1")
        assert result is False

    @patch(f"{MODULE}.acquire_lock")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_show_subprocess_error_returns_false(
        self, mock_agent, mock_run, mock_lock,
    ):
        """Initial show raises CalledProcessError → False."""
        mock_lock.return_value = contextlib.nullcontext()
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd", stderr="show failed")

        result = assign_and_sync_item("item-1")
        assert result is False


# ===================================================================
# unassign_item
# ===================================================================

class TestUnassignItem:
    """Tests for unassign_item."""

    @patch(f"{MODULE}.run_bd_sync_with_retry")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_success_status_reset_and_sync(self, mock_agent, mock_run, mock_sync):
        mock_run.return_value = _completed(stderr="")
        mock_sync.return_value = _completed()

        result = unassign_item("item-1")
        assert result is True
        mock_run.assert_called_once()
        mock_sync.assert_called_once()

    @patch(f"{MODULE}.run_bd_sync_with_retry")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_stderr_error_falls_back_to_status_only(self, mock_agent, mock_run, mock_sync):
        """First attempt has error in stderr → fallback to status-only."""
        # First call: stderr has error → raises internally
        # Second call (fallback): succeeds
        mock_run.side_effect = [
            _completed(stderr="error: invalid argument '-a'"),
            _completed(stderr=""),
        ]
        mock_sync.return_value = _completed()

        result = unassign_item("item-1")
        assert result is True
        assert mock_run.call_count == 2

    @patch(f"{MODULE}.run_bd_sync_with_retry")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_both_attempts_fail_returns_false(self, mock_agent, mock_run, mock_sync):
        """Both update attempts fail → False."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd", stderr="fail")

        result = unassign_item("item-1")
        assert result is False

    @patch(f"{MODULE}.run_bd_sync_with_retry")
    @patch(f"{MODULE}._run_bd")
    @patch(f"{MODULE}.get_agent_name", return_value="pokepoke_test_agent")
    def test_sync_failure_after_unassign_still_returns_true(
        self, mock_agent, mock_run, mock_sync,
    ):
        """Sync fails but unassign succeeded → warning logged, True returned."""
        mock_run.return_value = _completed(stderr="")
        mock_sync.return_value = _completed(returncode=1, stderr="sync error")

        result = unassign_item("item-1")
        assert result is True


# ===================================================================
# close_item
# ===================================================================

class TestCloseItem:
    """Tests for close_item."""

    @patch(f"{MODULE}._run_bd_with_retry")
    def test_success_returns_true(self, mock_retry):
        mock_retry.return_value = _completed()
        assert close_item("item-1") is True
        mock_retry.assert_called_once_with(["close", "item-1", "--reason", "Completed"])

    @patch(f"{MODULE}._run_bd_with_retry")
    def test_called_process_error_returns_false(self, mock_retry):
        mock_retry.side_effect = subprocess.CalledProcessError(1, "bd")
        assert close_item("item-1") is False

    @patch(f"{MODULE}._run_bd_with_retry")
    def test_timeout_expired_returns_false(self, mock_retry):
        mock_retry.side_effect = subprocess.TimeoutExpired("bd", 30)
        assert close_item("item-1") is False


# ===================================================================
# fail_task
# ===================================================================

class TestFailTask:
    """Tests for fail_task."""

    @patch(f"{MODULE}.add_comment", return_value=True)
    @patch("pokepoke.beads.beads_item_stats_store.record_item_failed")
    def test_success_adds_comment_and_records_stats(self, mock_stats, mock_comment):
        result = fail_task("item-1", "something broke")
        assert result is True
        mock_comment.assert_called_once()
        mock_stats.assert_called_once_with("item-1", agent_type="work")

    @patch(f"{MODULE}.add_comment", return_value=False)
    @patch("pokepoke.beads.beads_item_stats_store.record_item_failed")
    def test_comment_fails_but_stats_succeed(self, mock_stats, mock_comment):
        result = fail_task("item-1", "reason")
        assert result is False

    @patch(f"{MODULE}.add_comment", return_value=True)
    @patch(
        "pokepoke.beads.beads_item_stats_store.record_item_failed",
        side_effect=RuntimeError("db error"),
    )
    def test_stats_recording_fails_logs_warning(self, mock_stats, mock_comment):
        result = fail_task("item-1", "reason")
        # Comment succeeded, so return True
        assert result is True

    @patch(f"{MODULE}.add_comment", return_value=True)
    @patch("pokepoke.beads.beads_item_stats_store.record_item_failed")
    def test_reason_truncation_at_500_chars(self, mock_stats, mock_comment):
        long_reason = "x" * 600
        fail_task("item-1", long_reason)
        call_args = mock_comment.call_args[0]
        comment_text = call_args[1]
        assert "x" * 500 in comment_text
        assert "x" * 501 not in comment_text


# ===================================================================
# block_item
# ===================================================================

class TestBlockItem:
    """Tests for block_item."""

    @patch(f"{MODULE}.add_comment", return_value=True)
    @patch(f"{MODULE}._run_bd_with_retry")
    def test_success_updates_status_and_adds_comment(self, mock_retry, mock_comment):
        mock_retry.return_value = _completed()
        result = block_item("item-1", "needs human review")
        assert result is True
        mock_retry.assert_called_once_with(["update", "item-1", "--status", "blocked"])
        mock_comment.assert_called_once()

    @patch(f"{MODULE}._run_bd_with_retry")
    def test_update_fails_returns_false(self, mock_retry):
        mock_retry.side_effect = subprocess.CalledProcessError(1, "bd")
        result = block_item("item-1", "reason")
        assert result is False


# ===================================================================
# defer_item
# ===================================================================

class TestDeferItem:
    """Tests for defer_item."""

    @patch(f"{MODULE}.add_comment", return_value=True)
    @patch(f"{MODULE}._run_bd_with_retry")
    def test_success_updates_status_with_label(self, mock_retry, mock_comment):
        mock_retry.return_value = _completed()
        result = defer_item("item-1", "too complex")
        assert result is True
        call_args = mock_retry.call_args[0][0]
        assert "--status" in call_args
        assert "backlog" in call_args
        assert "--add-label" in call_args
        assert "needs-decomposition" in call_args

    @patch(f"{MODULE}._run_bd_with_retry")
    def test_update_fails_returns_false(self, mock_retry):
        mock_retry.side_effect = subprocess.CalledProcessError(1, "bd")
        result = defer_item("item-1", "reason")
        assert result is False


# ===================================================================
# add_comment
# ===================================================================

class TestAddComment:
    """Tests for add_comment."""

    @patch(f"{MODULE}._run_bd_with_retry")
    def test_success_returns_true(self, mock_retry):
        mock_retry.return_value = _completed()
        assert add_comment("item-1", "hello") is True
        mock_retry.assert_called_once_with(["comments", "add", "item-1", "hello"])

    @patch(f"{MODULE}._run_bd_with_retry")
    def test_failure_returns_false(self, mock_retry):
        mock_retry.side_effect = subprocess.CalledProcessError(1, "bd")
        assert add_comment("item-1", "hello") is False


# ===================================================================
# select_next_hierarchical_item
# ===================================================================

class TestSelectNextHierarchicalItem:
    """Tests for select_next_hierarchical_item."""

    def test_empty_list_returns_none(self):
        assert select_next_hierarchical_item([]) is None

    def test_regular_tasks_sorted_by_priority(self):
        low = _make_item(id="low", priority=10)
        high = _make_item(id="high", priority=1)
        result = select_next_hierarchical_item([low, high])
        assert result.id == "high"

    def test_skips_human_required_items(self):
        human = _make_item(id="human", labels=["human-required"])
        normal = _make_item(id="normal", priority=2)
        result = select_next_hierarchical_item([human, normal])
        assert result.id == "normal"

    def test_all_human_required_returns_none(self):
        human1 = _make_item(id="h1", labels=["human-required"])
        human2 = _make_item(id="h2", labels=["human-required"])
        assert select_next_hierarchical_item([human1, human2]) is None

    @patch(f"{MODULE}._resolve_with_timeout")
    def test_epic_resolved_to_leaf_task(self, mock_resolve):
        leaf = _make_item(id="leaf-task", issue_type="task")
        mock_resolve.return_value = leaf
        epic = _make_item(id="epic-1", issue_type="epic", priority=1)

        result = select_next_hierarchical_item([epic])
        assert result.id == "leaf-task"

    @patch(f"{MODULE}._resolve_with_timeout")
    def test_epic_resolution_fails_skips(self, mock_resolve):
        """resolve returns None → skip epic, try next."""
        mock_resolve.return_value = None
        epic = _make_item(id="epic-1", issue_type="epic", priority=1)
        task = _make_item(id="task-1", issue_type="task", priority=2)

        result = select_next_hierarchical_item([epic, task])
        assert result.id == "task-1"

    @patch(f"{MODULE}._resolve_with_timeout")
    def test_epic_resolution_timeout_skips(self, mock_resolve):
        """resolve returns None on timeout → skip epic."""
        mock_resolve.return_value = None
        epic = _make_item(id="epic-1", issue_type="feature", priority=1)

        result = select_next_hierarchical_item([epic])
        assert result is None


# ===================================================================
# _resolve_with_timeout
# ===================================================================

class TestResolveWithTimeout:
    """Tests for _resolve_with_timeout."""

    @patch(f"{MODULE}.resolve_to_leaf_task")
    def test_success_returns_resolved_item(self, mock_resolve):
        leaf = _make_item(id="leaf")
        mock_resolve.return_value = leaf
        item = _make_item(id="epic", issue_type="epic")

        result = _resolve_with_timeout(item, timeout=5)
        assert result is not None
        assert result.id == "leaf"

    @patch(f"{MODULE}._resolve_pool")
    def test_timeout_returns_none(self, mock_pool):
        import concurrent.futures
        mock_future = MagicMock()
        mock_future.result.side_effect = concurrent.futures.TimeoutError()
        mock_pool.submit.return_value = mock_future

        item = _make_item(id="epic", issue_type="epic")
        result = _resolve_with_timeout(item, timeout=1)
        assert result is None

    @patch(f"{MODULE}._resolve_pool")
    def test_exception_returns_none(self, mock_pool):
        mock_future = MagicMock()
        mock_future.result.side_effect = RuntimeError("resolve exploded")
        mock_pool.submit.return_value = mock_future

        item = _make_item(id="epic", issue_type="epic")
        result = _resolve_with_timeout(item, timeout=5)
        assert result is None
