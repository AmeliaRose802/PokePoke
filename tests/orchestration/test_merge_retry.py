"""Tests for merge-retry fast-path: gate-passed items skip work+gate on retry.

When a work item passes the gate but fails at merge, the orchestrator
sets a merge_retry flag in beads metadata. On re-pickup, if the worktree
exists with commits, process_work_item skips work+gate and jumps straight
to the merge step.
"""

from unittest.mock import patch

from pokepoke.orchestration.finalization import ResultContext, _finalize_item_result
from pokepoke.types import WorkItemResult
from pokepoke.types_agent import CopilotResult
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats


def _item(**overrides) -> BeadsWorkItem:
    defaults = dict(
        id="task-mr-1", title="Merge retry test", description="",
        status="open", priority=1, issue_type="task",
    )
    defaults.update(overrides)
    return BeadsWorkItem(**defaults)


# ═══════════════════════════════════════════════════════════════════════════
# WorkItemResult.failure_stage field
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkItemResultFailureStage:
    """Verify failure_stage field on WorkItemResult."""

    def test_default_is_none(self) -> None:
        r = WorkItemResult(success=True, request_count=1)
        assert r.failure_stage is None

    def test_merge_failure_stage(self) -> None:
        r = WorkItemResult(success=False, request_count=1, failure_stage="merge")
        assert r.failure_stage == "merge"


# ═══════════════════════════════════════════════════════════════════════════
# _handle_success sets failure_stage="merge" when merge fails
# ═══════════════════════════════════════════════════════════════════════════


class TestHandleSuccessMergeFailure:
    """When finalize_work_item returns False but gate passed, failure_stage='merge'."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=False)
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_merge_failure_sets_failure_stage(
        self, _banner, _set, _finalize, _tui, tmp_path,
    ) -> None:
        result = CopilotResult(
            work_item_id="task-mr-1", success=True, attempt_count=1,
            session_id="test-session",
        )
        wi_result, finalized = _finalize_item_result(ResultContext(
            result=result, item=_item(), worktree_path=tmp_path,
            selected_model="gpt-4", start_time=0.0, request_count=1,
            accumulated_stats=AgentStats(), cleanup_agent_runs=0,
            gate_agent_runs=1, gate_success=True,
            run_logger=None, item_logger=None,
            base_agent_id="agent-1", run_beta_test=False,
        ))
        assert finalized is False
        assert wi_result.success is False
        assert wi_result.failure_stage == "merge"
        assert wi_result.failure_reason is not None

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=False)
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_merge_failure_no_gate_does_not_set_stage(
        self, _banner, _set, _finalize, _tui, tmp_path,
    ) -> None:
        """When gate did NOT pass (gate_success=False), failure_stage stays None."""
        result = CopilotResult(
            work_item_id="task-mr-1", success=True, attempt_count=1,
            session_id="test-session",
        )
        wi_result, finalized = _finalize_item_result(ResultContext(
            result=result, item=_item(), worktree_path=tmp_path,
            selected_model="gpt-4", start_time=0.0, request_count=1,
            accumulated_stats=AgentStats(), cleanup_agent_runs=0,
            gate_agent_runs=0, gate_success=False,
            run_logger=None, item_logger=None,
            base_agent_id="agent-1", run_beta_test=False,
        ))
        assert finalized is False
        assert wi_result.failure_stage is None

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_success_does_not_set_failure_stage(
        self, _banner, _set, _finalize, _tui, tmp_path,
    ) -> None:
        result = CopilotResult(
            work_item_id="task-mr-1", success=True, attempt_count=1,
            session_id="test-session",
        )
        wi_result, finalized = _finalize_item_result(ResultContext(
            result=result, item=_item(), worktree_path=tmp_path,
            selected_model="gpt-4", start_time=0.0, request_count=1,
            accumulated_stats=AgentStats(), cleanup_agent_runs=0,
            gate_agent_runs=1, gate_success=True,
            run_logger=None, item_logger=None,
            base_agent_id="agent-1", run_beta_test=False,
        ))
        assert finalized is True
        assert wi_result.success is True
        assert wi_result.failure_stage is None


# ═══════════════════════════════════════════════════════════════════════════
# beads_metadata merge_retry helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestBeadsMetadataMergeRetry:
    """Test set_merge_retry / clear_merge_retry."""

    @patch("pokepoke.beads.beads_metadata._set_metadata", return_value=True)
    @patch("pokepoke.beads.beads_metadata._get_metadata", return_value={})
    def test_set_merge_retry(self, mock_get, mock_set) -> None:
        from pokepoke.beads.beads_metadata import set_merge_retry
        assert set_merge_retry("item-1") is True
        mock_set.assert_called_once_with("item-1", {"merge_retry": True})

    @patch("pokepoke.beads.beads_metadata._set_metadata", return_value=True)
    @patch("pokepoke.beads.beads_metadata._get_metadata", return_value={"merge_retry": True, "other": "val"})
    def test_clear_merge_retry(self, mock_get, mock_set) -> None:
        from pokepoke.beads.beads_metadata import clear_merge_retry
        assert clear_merge_retry("item-1") is True
        # merge_retry should be removed but other keys preserved
        mock_set.assert_called_once_with("item-1", {"other": "val"})

    @patch("pokepoke.beads.beads_metadata._get_metadata", return_value=None)
    def test_set_merge_retry_metadata_fetch_fails(self, mock_get) -> None:
        from pokepoke.beads.beads_metadata import set_merge_retry
        assert set_merge_retry("item-1") is False

    @patch("pokepoke.beads.beads_metadata._set_metadata", return_value=False)
    @patch("pokepoke.beads.beads_metadata._get_metadata", return_value={})
    def test_set_merge_retry_write_fails(self, mock_get, mock_set) -> None:
        from pokepoke.beads.beads_metadata import set_merge_retry
        assert set_merge_retry("item-1") is False

    @patch("pokepoke.beads.beads_metadata._get_metadata", return_value=None)
    def test_clear_merge_retry_fetch_fails(self, mock_get) -> None:
        from pokepoke.beads.beads_metadata import clear_merge_retry
        assert clear_merge_retry("item-1") is False


# ═══════════════════════════════════════════════════════════════════════════
# Merge-retry fast-path in process_work_item
# ═══════════════════════════════════════════════════════════════════════════

_WF = "pokepoke.orchestration.workflow"
_WFL = "pokepoke.orchestration.workflow_loop"
_FIN = "pokepoke.orchestration.finalization"


class TestMergeRetryFastPath:
    """Test that merge_retry items skip work+gate and go straight to merge."""

    @patch(f"{_FIN}.finalize_work_item", return_value=True)
    @patch(f"{_WFL}.get_gate_step_tracker")
    @patch(f"{_WF}.select_model_for_item", return_value="gpt-4")
    @patch(f"{_WF}.get_assignment_for_item", return_value=(None, None))
    @patch(f"{_WF}.get_config")
    @patch(f"{_WF}.assign_and_sync_item", return_value=True)
    @patch(f"{_WF}.setup_worktree")
    @patch(f"{_WF}.invoke_copilot")
    @patch("pokepoke.beads.beads_metadata.clear_merge_retry", return_value=True)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=3)
    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch(f"{_WF}.terminal_ui")
    def test_merge_retry_skips_work_and_gate(
        self, _tui_wf, _tui_fin, _commits_ahead, _clear_retry,
        mock_invoke, mock_setup, _assign, mock_config, _assign_for,
        _select_model, _tracker, mock_finalize, tmp_path,
    ) -> None:
        """When merge_retry is set and worktree has commits, invoke_copilot is NOT called."""
        cfg = mock_config.return_value
        cfg.ai_backend.provider = "copilot"
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 1
        cfg.max_gate_rejections_per_item = 3
        cfg.gate_agent_enabled = True
        cfg.gate_reverify_resume_enabled = False

        mock_setup.return_value = tmp_path

        item = _item(metadata={"merge_retry": True})

        from pokepoke.orchestration.workflow import process_work_item

        with (
            patch(f"{_WF}.register_agent"),
            patch(f"{_WF}.unregister_agent"),
            patch(f"{_WF}.set_current_work_item_id"),
            patch(f"{_WF}.set_current_repo_name"),
            patch(f"{_WF}.get_agent_name", return_value="test"),
            patch("pokepoke.orchestration.finalization.set_terminal_banner"),
            patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b"),
        ):
            result = process_work_item(item, interactive=False)

        # The key assertion: invoke_copilot was never called
        mock_invoke.assert_not_called()
        # finalize_work_item WAS called (merge path)
        mock_finalize.assert_called_once()
        assert result.success is True

    @patch(f"{_FIN}.finalize_work_item", return_value=False)
    @patch(f"{_WFL}.get_gate_step_tracker")
    @patch(f"{_WF}.select_model_for_item", return_value="gpt-4")
    @patch(f"{_WF}.get_assignment_for_item", return_value=(None, None))
    @patch(f"{_WF}.get_config")
    @patch(f"{_WF}.assign_and_sync_item", return_value=True)
    @patch(f"{_WF}.setup_worktree")
    @patch(f"{_WF}.invoke_copilot")
    @patch("pokepoke.beads.beads_metadata.clear_merge_retry", return_value=True)
    @patch("pokepoke.beads.beads_metadata.set_merge_retry", return_value=True)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=3)
    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch(f"{_WF}.terminal_ui")
    def test_merge_retry_still_fails_re_sets_flag(
        self, _tui_wf, _tui_fin, _commits_ahead, mock_set_retry,
        _clear_retry, mock_invoke, mock_setup, _assign, mock_config,
        _assign_for, _select_model, _tracker, mock_finalize, tmp_path,
    ) -> None:
        """When merge-retry fast-path still fails at merge, re-set the flag."""
        cfg = mock_config.return_value
        cfg.ai_backend.provider = "copilot"
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 1
        cfg.max_gate_rejections_per_item = 3
        cfg.gate_agent_enabled = True
        cfg.gate_reverify_resume_enabled = False

        mock_setup.return_value = tmp_path

        item = _item(metadata={"merge_retry": True})

        from pokepoke.orchestration.work_item_session import WorkItemSession
        from pokepoke.orchestration.workflow import process_work_item

        with (
            patch(f"{_WF}.register_agent"),
            patch(f"{_WF}.unregister_agent"),
            patch(f"{_WF}.set_current_work_item_id"),
            patch(f"{_WF}.set_current_repo_name"),
            patch(f"{_WF}.get_agent_name", return_value="test"),
            patch("pokepoke.orchestration.finalization.set_terminal_banner"),
            patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b"),
            patch.object(WorkItemSession, "cleanup_on_failure"),
        ):
            result = process_work_item(item, interactive=False)

        mock_invoke.assert_not_called()
        assert result.success is False
        assert result.failure_stage == "merge"
        # Flag should be re-set for next attempt
        mock_set_retry.assert_called_once_with("task-mr-1")

    @patch(f"{_WF}._maybe_decompose")
    @patch(f"{_WF}.save_worker_context")
    @patch(f"{_WF}.is_shutting_down", side_effect=[False, True])
    @patch(f"{_WF}.terminal_ui")
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=0)
    @patch("pokepoke.beads.beads_metadata.clear_merge_retry", return_value=True)
    @patch(f"{_WF}.invoke_copilot")
    @patch(f"{_WF}.setup_worktree")
    @patch(f"{_WF}.assign_and_sync_item", return_value=True)
    @patch(f"{_WF}.get_config")
    @patch(f"{_WF}.get_assignment_for_item", return_value=(None, None))
    @patch(f"{_WF}.select_model_for_item", return_value="gpt-4")
    @patch(f"{_WFL}.get_gate_step_tracker")
    def test_merge_retry_no_commits_falls_through(
        self, _tracker, _select_model, _assign_for, mock_config,
        _assign, mock_setup, mock_invoke, _clear_retry,
        _commits_ahead, _tui_wf, _shutdown, _save_ctx, _decompose,
        tmp_path,
    ) -> None:
        """When merge_retry is set but worktree has 0 commits, fall through to normal pipeline."""
        cfg = mock_config.return_value
        cfg.ai_backend.provider = "copilot"
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 1
        cfg.max_gate_rejections_per_item = 3
        cfg.gate_agent_enabled = True
        cfg.gate_reverify_resume_enabled = False
        cfg.max_copilot_failure_retries = 0

        mock_setup.return_value = tmp_path

        # invoke_copilot returns failure to end the while loop
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-mr-1", success=False,
            error="shutdown", attempt_count=0,
            session_id="s1",
        )

        item = _item(metadata={"merge_retry": True})

        from pokepoke.orchestration.work_item_session import WorkItemSession
        from pokepoke.orchestration.workflow import process_work_item

        with (
            patch(f"{_WF}.register_agent"),
            patch(f"{_WF}.unregister_agent"),
            patch(f"{_WF}.set_current_work_item_id"),
            patch(f"{_WF}.set_current_repo_name"),
            patch(f"{_WF}.get_agent_name", return_value="test"),
            patch(f"{_WF}.verify_worktree_branch", return_value=None),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
            patch("pokepoke.orchestration.finalization.reconcile_completed_item", return_value=(False, {})),
            patch("pokepoke.orchestration.finalization.set_terminal_banner"),
            patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b"),
            patch("pokepoke.beads.beads_management.fail_task"),
            patch.object(WorkItemSession, "cleanup_on_failure"),
        ):
            result = process_work_item(item, interactive=False)

        # clear_merge_retry should have been called since 0 commits
        _clear_retry.assert_called_once_with("task-mr-1")
        # Should have fallen through and called invoke_copilot
        assert result.success is False

    @patch(f"{_WF}._maybe_decompose")
    @patch(f"{_WF}.save_worker_context")
    @patch(f"{_WF}.is_shutting_down", side_effect=[False, True])
    @patch(f"{_WF}.terminal_ui")
    @patch(f"{_WF}.invoke_copilot")
    @patch(f"{_WF}.setup_worktree")
    @patch(f"{_WF}.assign_and_sync_item", return_value=True)
    @patch(f"{_WF}.get_config")
    @patch(f"{_WF}.get_assignment_for_item", return_value=(None, None))
    @patch(f"{_WF}.select_model_for_item", return_value="gpt-4")
    @patch(f"{_WFL}.get_gate_step_tracker")
    def test_no_merge_retry_goes_through_normal_pipeline(
        self, _tracker, _select_model, _assign_for, mock_config,
        _assign, mock_setup, mock_invoke, _tui_wf, _shutdown,
        _save_ctx, _decompose, tmp_path,
    ) -> None:
        """Without merge_retry flag, process_work_item runs the normal pipeline."""
        cfg = mock_config.return_value
        cfg.ai_backend.provider = "copilot"
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 1
        cfg.max_gate_rejections_per_item = 3
        cfg.gate_agent_enabled = True
        cfg.gate_reverify_resume_enabled = False
        cfg.max_copilot_failure_retries = 0

        mock_setup.return_value = tmp_path
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-mr-1", success=False,
            error="shutdown", attempt_count=0,
            session_id="s1",
        )

        item = _item()  # No merge_retry in metadata

        from pokepoke.orchestration.work_item_session import WorkItemSession
        from pokepoke.orchestration.workflow import process_work_item

        with (
            patch(f"{_WF}.register_agent"),
            patch(f"{_WF}.unregister_agent"),
            patch(f"{_WF}.set_current_work_item_id"),
            patch(f"{_WF}.set_current_repo_name"),
            patch(f"{_WF}.get_agent_name", return_value="test"),
            patch(f"{_WF}.verify_worktree_branch", return_value=None),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
            patch("pokepoke.orchestration.finalization.reconcile_completed_item", return_value=(False, {})),
            patch("pokepoke.orchestration.finalization.set_terminal_banner"),
            patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b"),
            patch("pokepoke.beads.beads_management.fail_task"),
            patch.object(WorkItemSession, "cleanup_on_failure"),
        ):
            result = process_work_item(item, interactive=False)

        # invoke_copilot WAS called (normal pipeline)
        mock_invoke.assert_called_once()
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════
# Normal pipeline sets merge_retry on merge-stage failure
# ═══════════════════════════════════════════════════════════════════════════


class TestNormalPipelineSetsMergeRetry:
    """Verify that the normal pipeline sets merge_retry when gate passes but merge fails."""

    @patch(f"{_FIN}.finalize_work_item", return_value=False)
    @patch(f"{_WF}.run_cleanup_with_timeout", return_value=(True, 0))
    @patch(f"{_WFL}.get_gate_step_tracker")
    @patch(f"{_WF}.select_model_for_item", return_value="gpt-4")
    @patch(f"{_WF}.get_assignment_for_item", return_value=(None, None))
    @patch(f"{_WF}.get_config")
    @patch(f"{_WF}.assign_and_sync_item", return_value=True)
    @patch(f"{_WF}.setup_worktree")
    @patch(f"{_WF}.invoke_copilot")
    @patch("pokepoke.beads.beads_metadata.set_merge_retry", return_value=True)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=1)
    @patch("pokepoke.git.git_operations.has_uncommitted_changes", return_value=False)
    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch(f"{_WF}.terminal_ui")
    def test_gate_pass_merge_fail_sets_merge_retry(
        self, _tui_wf, _tui_fin, _uncommitted, _commits,
        mock_set_retry, mock_invoke, mock_setup, _assign, mock_config,
        _assign_for, _select_model, _tracker, _cleanup, mock_finalize,
        tmp_path,
    ) -> None:
        from pokepoke.orchestration.gate_agent_loop import GateLoopResult
        cfg = mock_config.return_value
        cfg.ai_backend.provider = "copilot"
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 1
        cfg.max_gate_rejections_per_item = 3
        cfg.gate_agent_enabled = True
        cfg.gate_reverify_resume_enabled = False

        mock_setup.return_value = tmp_path
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-mr-1", success=True,
            output="done", attempt_count=1,
            session_id="s1",
        )

        item = _item()

        from pokepoke.orchestration.work_item_session import WorkItemSession
        from pokepoke.orchestration.workflow import process_work_item

        with (
            patch(f"{_WF}.register_agent"),
            patch(f"{_WF}.unregister_agent"),
            patch(f"{_WF}.set_current_work_item_id"),
            patch(f"{_WF}.set_current_repo_name"),
            patch(f"{_WF}.get_agent_name", return_value="test"),
            patch(f"{_WF}.verify_worktree_branch", return_value=None),
            patch(f"{_WFL}.run_gate_loop", return_value=GateLoopResult(
                gate_success=True, gate_agent_runs=1,
                gate_rejection_count=0, exceeded_max=False,
            )),
            patch("pokepoke.orchestration.finalization.set_terminal_banner"),
            patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b"),
            patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False),
            patch.object(WorkItemSession, "cleanup_on_failure"),
        ):
            result = process_work_item(item, interactive=False)

        assert result.success is False
        assert result.failure_stage == "merge"
        mock_set_retry.assert_called_once_with("task-mr-1")
