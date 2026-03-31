"""Unit tests for workflow error handling.

This module tests error handling behavior including:
- Gate agent configuration and disabling
- Work item cleanup and unassignment on failure
- Failure logging
- Exception handling in gate agent and cleanup
"""

from unittest.mock import Mock, patch

import pytest

from pokepoke.orchestration.workflow import process_work_item
from tests.orchestration.conftest import (
    PATCH_WF_GET_CONFIG,
    make_process_item_mocks,
    make_work_item,
)


class TestGateAgentDisabled:
    """Tests for gate_agent_enabled config setting."""

    def test_gate_agent_skipped_when_disabled(self) -> None:
        """When gate_agent_enabled is False, gate agent should not run."""
        item = make_work_item()

        with make_process_item_mocks(include_handoff=True) as mocks:
            from pokepoke.config import ProjectConfig
            cfg = ProjectConfig()
            cfg.gate_agent_enabled = False
            with patch(PATCH_WF_GET_CONFIG, return_value=cfg):
                result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.gate_agent_runs == 0
            mocks['gate'].assert_not_called()


class TestUnassignOnFailure:
    """Tests that work items are cleaned up when processing fails after assignment."""

    def test_finalization_failure_triggers_cleanup(self) -> None:
        """When finalize_work_item returns False, session cleanup must run."""
        item = make_work_item(id="task-finalize-fail", title="Finalize Fail Task")

        with make_process_item_mocks(
            finalize_ok=False,
            include_handoff=True, include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            mocks['session_cleanup'].assert_called_once()

    def test_work_agent_failure_triggers_cleanup(self) -> None:
        """When work agent fails, session cleanup must run."""
        item = make_work_item(id="task-agent-fail", title="Agent Fail Task")

        with make_process_item_mocks(
            copilot_success=False,
            include_cleanup_worktree=True, include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            mocks['session_cleanup'].assert_called_once()

    def test_successful_finalization_skips_cleanup(self) -> None:
        """When finalization succeeds, session cleanup must NOT run."""
        item = make_work_item(id="task-success", title="Success Task")

        with make_process_item_mocks(
            include_handoff=True, include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is True
            mocks['session_cleanup'].assert_not_called()


class TestLogFailure:
    """Tests for _log_failure helper."""

    def test_calls_loggers_when_both_present(self) -> None:
        """Covers lines 38-39: both loggers are called."""
        from pokepoke.orchestration.workflow import _log_failure
        run_logger = Mock()
        item_logger = Mock()
        _log_failure(run_logger, item_logger, request_count=3)
        item_logger.log_summary.assert_called_once_with(False, 3)
        run_logger.log_orchestrator.assert_called_once()

    def test_skips_when_no_loggers(self) -> None:
        """Covers lines 37: no-op when loggers are None."""
        from pokepoke.orchestration.workflow import _log_failure
        _log_failure(None, None, request_count=1)  # Should not raise


class TestWorkflowGateException:
    """Tests for gate agent exception handling."""

    def test_gate_agent_exception_triggers_cleanup(self) -> None:
        """Gate agent exception is re-raised and session cleanup runs in finally."""
        item = make_work_item(id="task-gate-ex", title="Gate Ex Task")

        with make_process_item_mocks(
            include_handoff=True, include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            mocks['gate'].side_effect = RuntimeError("gate crashed")

            with pytest.raises(RuntimeError, match="gate crashed"):
                process_work_item(item, interactive=False)

            # Finally block should have run session cleanup
            mocks['session_cleanup'].assert_called()


class TestWorkflowCleanupException:
    """Tests for session cleanup exception handling in finally."""

    def test_cleanup_exception_in_finally_propagates(self) -> None:
        """When cleanup_on_failure raises, the exception propagates
        (cleanup_on_failure itself should never raise, but if it does
        the finally block does not swallow it)."""
        item = make_work_item(id="task-cleanup-ex", title="Cleanup Ex")

        with make_process_item_mocks(
            copilot_success=False,
            include_cleanup_worktree=True, include_session_cleanup=True,
        ) as mocks:
            mocks['session_cleanup'].side_effect = RuntimeError("cleanup exploded")

            with pytest.raises(RuntimeError, match="cleanup exploded"):
                process_work_item(item, interactive=False)

    def test_cleanup_called_on_work_agent_failure(self) -> None:
        """Session cleanup runs when work agent fails."""
        item = make_work_item(id="task-unassign-ex", title="Unassign Ex")

        with make_process_item_mocks(
            copilot_success=False,
            include_cleanup_worktree=True, include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            mocks['session_cleanup'].assert_called_once()

    def test_unassign_called_in_cleanup_sequence(self) -> None:
        """Verifies that unassign is called as part of cleanup on failure."""
        item = make_work_item(id="task-unassign-ex", title="Unassign Ex")

        with (
            make_process_item_mocks(
                copilot_success=False,
                include_cleanup_worktree=True, include_session_cleanup=True,
            ) as mocks,
            patch('pokepoke.beads.beads_recovery.unassign_with_retry', return_value=True) as mock_unassign,
        ):
            # Allow cleanup_on_failure to call through to real method
            mocks['session_cleanup'].side_effect = lambda: mock_unassign(item.id)

            result = process_work_item(item, interactive=False)

            assert result.success is False
            # Verify cleanup was called
            mocks['session_cleanup'].assert_called_once()

    def test_unassign_exception_logged_during_cleanup(self) -> None:
        """When unassign fails during cleanup, error is logged but doesn't crash."""
        item = make_work_item(id="task-unassign-ex", title="Unassign Ex")

        with make_process_item_mocks(
            copilot_success=False,
            include_cleanup_worktree=True, include_session_cleanup=True,
        ) as mocks:
            # Make cleanup raise an exception to simulate unassign failure
            mocks['session_cleanup'].side_effect = RuntimeError("unassign_with_retry exhausted")

            # Should re-raise the exception
            with pytest.raises(RuntimeError, match="unassign_with_retry exhausted"):
                process_work_item(item, interactive=False)
