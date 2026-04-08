"""Tests for auto-defer behavior when gate rejection cap is reached.

Verifies that items are deferred to backlog with needs-decomposition label
after exceeding the gate rejection cap, rather than just being blocked.
"""

from unittest.mock import MagicMock, patch

from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.workflow import process_work_item
from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    CopilotResult,
    GateAgentResult,
)


def _item(**kwargs) -> BeadsWorkItem:
    defaults = dict(
        id="defer-1", title="Complex task", status="open",
        priority=1, issue_type="task", metadata=None,
    )
    defaults.update(kwargs)
    return BeadsWorkItem(**defaults)


def _branch_ok():
    return MagicMock(stdout="task/defer-1\n", returncode=0)


class TestPreLoopGateRejectionDefer:
    """Test that gate rejection cap pre-check is handled at the selection level.

    The pre-loop cap check was moved from process_work_item to the selection
    phase (_filter_available / select_multiple_items). process_work_item now
    reads gate_rejection_count from item.metadata instead of calling bd show.
    Selection-level filtering tests are in test_work_item_selection_coverage.py.
    """

    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("a", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    def test_reads_gate_rejection_count_from_metadata(
        self, mock_agent, mock_banner_fmt, mock_set_banner, mock_ui,
        mock_assignment, mock_model, mock_config,
        mock_register, mock_unregister,
    ):
        """process_work_item should use item.metadata for gate_rejection_count."""
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0,
            max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )

        # Item below cap proceeds to assign (which fails) - no bd show needed
        item = _item(metadata={"gate_rejection_count": 1})
        with patch(
            "pokepoke.orchestration.workflow.assign_and_sync_item",
            return_value=False,
        ):
            result = process_work_item(item, interactive=False)

            assert result.success is False
            # Failure is from assign, not from cap check
            assert "assign" in (result.failure_reason or "").lower()

    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("a", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    def test_no_metadata_defaults_to_zero(
        self, mock_agent, mock_banner_fmt, mock_set_banner, mock_ui,
        mock_assignment, mock_model, mock_config,
        mock_register, mock_unregister,
    ):
        """Item without metadata should default gate_rejection_count to 0."""
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0,
            max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )

        # Item with no metadata proceeds to assign (which fails)
        with patch(
            "pokepoke.orchestration.workflow.assign_and_sync_item",
            return_value=False,
        ):
            result = process_work_item(_item(), interactive=False)

            assert result.success is False
            # Failure is from assign - item was not rejected at cap
            assert "assign" in (result.failure_reason or "").lower()


class TestInLoopGateRejectionDefer:
    """Test that items reaching gate rejection cap during processing are auto-deferred."""

    @patch("pokepoke.git.git_helpers.run_git", return_value=_branch_ok())
    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch.object(WorkItemSession, "cleanup_on_failure")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=False)
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=1)
    @patch("pokepoke.orchestration.workflow.run_cleanup_with_timeout", return_value=(True, 0))
    @patch("pokepoke.orchestration.workflow.invoke_copilot")
    @patch("pokepoke.orchestration.workflow.build_prompt_from_work_item", return_value="prompt")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("a", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree")
    @patch("pokepoke.orchestration.workflow.is_shutting_down", return_value=False)
    def test_defers_after_reaching_cap_in_loop(
        self, mock_shutdown, mock_setup, mock_assign, mock_agent,
        mock_banner_fmt, mock_set_banner, mock_ui,
        mock_assignment, mock_model, mock_config,
        mock_prompt, mock_copilot, mock_cleanup_timeout,
        mock_ahead, mock_uncommitted, mock_finalize,
        mock_cleanup_wt, mock_session, mock_register,
        mock_unregister, mock_run_git, tmp_path,
    ):
        """Gate rejection cap reached during processing should auto-defer."""
        mock_setup.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0,
            max_gate_rejections_per_item=1,  # Low cap so first rejection triggers defer
            ai_backend=MagicMock(provider="copilot"),
        )
        mock_copilot.return_value = CopilotResult(
            work_item_id="defer-1", success=True, attempt_count=1,
            output="done", stats=AgentStats(input_tokens=100),
        )

        with patch(
            "pokepoke.beads.beads_management.get_gate_rejection_count",
            return_value=0,
        ), patch(
            "pokepoke.orchestration.workflow.run_gate_agent",
            return_value=GateAgentResult(
                success=False, reason="Tests failing",
                crashed=False, is_timeout=False,
            ),
        ), patch(
            "pokepoke.beads.beads_management.increment_gate_rejection_count",
            return_value=1,
        ), patch(
            "pokepoke.orchestration.workflow.defer_item"
        ) as mock_defer, patch(
            "pokepoke.orchestration.workflow.add_comment"
        ), patch(
            "pokepoke.orchestration.workflow._maybe_decompose"
        ), patch(
            "pokepoke.orchestration.workflow.save_worker_context"
        ), patch(
            "pokepoke.beads.beads_management.fail_task"
        ), patch(
            "pokepoke.beads.reconciliation.reconcile_completed_item",
            return_value=(False, {}),
        ):
            result = process_work_item(_item(), interactive=False)

            assert result.success is False
            mock_defer.assert_called_once()
            defer_reason = mock_defer.call_args[0][1]
            assert "gate rejection" in defer_reason.lower()
            assert "single agent session" in defer_reason.lower()


class TestFakeBeadsClientDefer:
    """Test that FakeBeadsClient properly supports defer_item."""

    def test_defer_sets_status_and_label(self) -> None:
        from tests.fakes import FakeBeadsClient

        client = FakeBeadsClient()
        item = BeadsWorkItem(
            id="t1", title="Test", status="open", priority=1, issue_type="task",
        )
        client.add_item(item)

        result = client.defer_item("t1", "Too complex")

        assert result is True
        assert client.items["t1"].status == "backlog"
        assert "needs-decomposition" in client.items["t1"].labels

    def test_defer_adds_comment(self) -> None:
        from tests.fakes import FakeBeadsClient

        client = FakeBeadsClient()
        item = BeadsWorkItem(
            id="t1", title="Test", status="open", priority=1, issue_type="task",
        )
        client.add_item(item)

        client.defer_item("t1", "Too complex")

        comments = client.get_comments("t1")
        assert any("Auto-deferred" in c for c in comments)

    def test_defer_records_call(self) -> None:
        from tests.fakes import FakeBeadsClient

        client = FakeBeadsClient()
        item = BeadsWorkItem(
            id="t1", title="Test", status="open", priority=1, issue_type="task",
        )
        client.add_item(item)

        client.defer_item("t1", "reason")

        assert client.call_count("defer_item") == 1

    def test_defer_fails_when_in_fail_methods(self) -> None:
        from tests.fakes import FakeBeadsClient

        client = FakeBeadsClient()
        item = BeadsWorkItem(
            id="t1", title="Test", status="open", priority=1, issue_type="task",
        )
        client.add_item(item)
        client.fail_methods.add("defer_item")

        result = client.defer_item("t1", "reason")

        assert result is False
        # Status should NOT have changed
        assert client.items["t1"].status == "open"

    def test_defer_does_not_duplicate_label(self) -> None:
        from tests.fakes import FakeBeadsClient

        client = FakeBeadsClient()
        item = BeadsWorkItem(
            id="t1", title="Test", status="open", priority=1, issue_type="task",
            labels=["needs-decomposition"],
        )
        client.add_item(item)

        client.defer_item("t1", "reason")

        assert client.items["t1"].labels.count("needs-decomposition") == 1
