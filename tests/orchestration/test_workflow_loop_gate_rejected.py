"""Tests for gate_rejected flag behavior in the workflow loop.

Verifies that when the gate rejection cap is exceeded, result.gate_rejected
is set to True while result.success preserves the agent's reported outcome.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pokepoke.orchestration.workflow_loop import run_workflow_loop
from pokepoke.types_agent import CopilotResult


def _make_cfg(**overrides):
    """Create a minimal config namespace for run_workflow_loop."""
    defaults = {
        "timeout_hours": 1,
        "max_timeout_restarts": 0,
        "gate_agent_enabled": True,
        "command_timeout": 300,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_global_config(**overrides):
    defaults = {
        "gate_agent_enabled": True,
        "max_copilot_failure_retries": 0,
        "gate_reverify_resume_enabled": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_item(**overrides):
    defaults = {"id": "task-1", "title": "Test item", "metadata": {}}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _noop(*a, **k):
    pass


def _noop_false(*a, **k):
    return False


def _noop_none(*a, **k):
    return None


def _extract_stats(result):
    return result.stats


def _no_retry(*a, **k):
    return (False, "")


def _fail_result(*, request_count, stats, cleanup_agent_runs, gate_agent_runs, failure_reason):
    from pokepoke.types import WorkItemResult
    return WorkItemResult(success=False, request_count=request_count)


def _make_gate_loop_result(*, gate_success=False, exceeded_max=False, feedback=None,
                           gate_rejection_count=0, gate_agent_runs=0,
                           session_id=None, last_output_summary=None):
    return SimpleNamespace(
        gate_success=gate_success,
        exceeded_max=exceeded_max,
        feedback=feedback,
        gate_rejection_count=gate_rejection_count,
        gate_agent_runs=gate_agent_runs,
        session_id=session_id,
        last_output_summary=last_output_summary,
    )


class _FakeUI:
    """Minimal UI stub for workflow loop."""
    class ui:  # noqa: N801
        @staticmethod
        def set_current_agent(*a, **k): pass

        @staticmethod
        def push_agent_status(*a, **k): pass

        @staticmethod
        def agent_output_for(*a, **k):
            from contextlib import nullcontext
            return nullcontext()


def _invoke_copilot_success(item, *, prompt, timeout, item_logger, model, cwd,
                            session_id, is_resume):
    return CopilotResult(
        work_item_id=item.id,
        success=True,
        output="Done",
        attempt_count=1,
        session_id="sid-1",
    )


def _invoke_copilot_failure(item, *, prompt, timeout, item_logger, model, cwd,
                            session_id, is_resume):
    return CopilotResult(
        work_item_id=item.id,
        success=False,
        error="Agent failed",
        attempt_count=1,
    )


def _run_loop(*, invoke_fn=None, gate_loop_side_effect=None, max_gate_rejections=3,
              is_shutting_down_calls=None, cfg_overrides=None,
              global_config_overrides=None, run_cleanup_return=None,
              check_sdk_invariant_return=False, maybe_retry_side_effect=None,
              verify_branch_return=None, handle_fail_fast_return=None,
              time_side_effect=None, beads_closed=False):
    """Helper to call run_workflow_loop with common defaults."""
    if invoke_fn is None:
        invoke_fn = _invoke_copilot_success

    # is_shutting_down returns False once then True to stop the loop
    if is_shutting_down_calls is None:
        is_shutting_down_calls = [False, True]
    shutdown_iter = iter(is_shutting_down_calls)

    item = _make_item()
    cfg = _make_cfg(**(cfg_overrides or {}))
    global_config = _make_global_config(**(global_config_overrides or {}))

    gate_mock = (
        MagicMock(side_effect=gate_loop_side_effect)
        if gate_loop_side_effect
        else MagicMock(return_value=_make_gate_loop_result(gate_success=True))
    )

    cleanup_return = run_cleanup_return if run_cleanup_return is not None else (True, 0)
    sdk_check = check_sdk_invariant_return
    retry_fn = (
        MagicMock(side_effect=maybe_retry_side_effect)
        if maybe_retry_side_effect
        else _no_retry
    )
    branch_fn = MagicMock(return_value=verify_branch_return)
    ff_return = handle_fail_fast_return if handle_fail_fast_return is not None else (None, None)

    import contextlib

    stack = contextlib.ExitStack()
    with stack:
        stack.enter_context(patch(
            "pokepoke.orchestration.workflow_loop.run_gate_loop", gate_mock
        ))
        stack.enter_context(patch(
            "pokepoke.orchestration.workflow_loop.build_prompt_from_work_item",
            return_value="test prompt",
        ))
        stack.enter_context(patch(
            "pokepoke.orchestration.workflow_loop.build_resume_prompt",
            return_value="resume prompt",
        ))
        stack.enter_context(patch(
            "pokepoke.orchestration.workflow_loop.get_gate_step_tracker",
            return_value=SimpleNamespace(
                start_work=_noop, work_done=_noop, cleanup_done=_noop,
                complete_step=_noop, fail_step=_noop, mark_failure=_noop,
                mark_success=_noop, gate_start=_noop, gate_disabled=_noop,
                gate_rejected_max=_noop, gate_rejected_retry=_noop,
                item_closed=_noop, begin_step=_noop, finish_run=_noop,
            ),
        ))
        stack.enter_context(patch(
            "pokepoke.beads.reconciliation.is_beads_item_closed",
            return_value=beads_closed,
        ))
        if time_side_effect is not None:
            stack.enter_context(patch("time.time", side_effect=time_side_effect))
        else:
            stack.enter_context(patch("time.time", return_value=0.0))
        stack.enter_context(patch("time.sleep"))

        result = run_workflow_loop(
            item=item,
            cfg=cfg,
            base_agent_id="agent-1",
            selected_model="gpt-4",
            selected_prompt_template=None,
            global_config=global_config,
            backend_provider="copilot",
            start_time=0.0,
            timeout_seconds=3600,
            max_gate_rejections=max_gate_rejections,
            worktree_cwd="/fake/worktree",
            pokepoke_root=Path("/fake/root"),
            run_logger=MagicMock(),
            item_logger=MagicMock(),
            session=None,
            previous_worker_context=None,
            worktree_resume_context=None,
            comment_fn=_noop,
            block_fn=_noop,
            defer_fn=_noop,
            invoke_copilot_fn=invoke_fn,
            run_cleanup_with_timeout_fn=MagicMock(return_value=cleanup_return),
            is_shutting_down_fn=lambda: next(shutdown_iter),
            apply_gate_feedback_fn=MagicMock(return_value=(["feedback"], 2)),
            check_sdk_invariant_fn=lambda *a, **k: sdk_check,
            combine_resume_contexts_fn=MagicMock(return_value=None),
            extract_agent_stats_fn=_extract_stats,
            fail_result_fn=_fail_result,
            handle_fail_fast_outcome_fn=MagicMock(return_value=ff_return),
            log_commit_status_fn=_noop,
            log_failure_fn=_noop,
            maybe_decompose_fn=_noop,
            maybe_retry_copilot_fn=retry_fn,
            ui_module=_FakeUI,
            get_agent_name_fn=MagicMock(return_value="pokepoke"),
            verify_worktree_branch_fn=branch_fn,
        )
    return result


class TestGateRejectedFlag:
    """Verify gate_rejected flag behavior in the workflow loop."""

    def test_exceeded_max_sets_gate_rejected_true(self):
        """When gate rejection cap is exceeded, result.gate_rejected is True
        and result.success remains True (preserving agent's reported outcome)."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_success,
            gate_loop_side_effect=[
                _make_gate_loop_result(exceeded_max=True, gate_rejection_count=3),
            ],
            max_gate_rejections=3,
            is_shutting_down_calls=[False],
        )
        result = loop_result.result
        assert result.gate_rejected is True
        assert result.success is True
        assert "Exceeded max gate rejections" in result.error

    def test_gate_pass_gate_rejected_false(self):
        """When gate passes normally, gate_rejected remains False."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_success,
            gate_loop_side_effect=[
                _make_gate_loop_result(gate_success=True),
            ],
            is_shutting_down_calls=[False],
        )
        result = loop_result.result
        assert result.gate_rejected is False
        assert result.success is True

    def test_agent_failure_gate_rejected_false(self):
        """When the agent actually fails, gate_rejected is False and
        result.success is False."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_failure,
            is_shutting_down_calls=[False],
        )
        result = loop_result.result
        assert result.gate_rejected is False
        assert result.success is False


class TestTimeoutExceeded:
    """Verify timeout and max-restart-exceeded paths."""

    def test_max_timeout_restarts_exceeded_returns_failure(self):
        """When elapsed >= timeout and max_timeout_restarts already hit,
        returns an immediate failure result."""
        # time.time() returns 4000 on every call → elapsed=4000 > 3600
        loop_result = _run_loop(
            is_shutting_down_calls=[False],
            cfg_overrides={"max_timeout_restarts": 0},
            time_side_effect=lambda: 4000.0,
        )
        assert loop_result.immediate_result is not None
        assert loop_result.immediate_result.success is False

    def test_timeout_restart_then_succeeds(self):
        """When timeout fires but restarts remain, the loop retries
        and can succeed on the next iteration."""
        call_count = 0

        def advancing_time():
            nonlocal call_count
            call_count += 1
            # First call: elapsed exceeds timeout (triggers restart)
            # After restart resets start_time, subsequent calls return 0-ish
            if call_count <= 2:
                return 4000.0
            return 4000.0  # new start_time is also 4000, so elapsed=0

        loop_result = _run_loop(
            is_shutting_down_calls=[False, False],
            cfg_overrides={"max_timeout_restarts": 2},
            time_side_effect=advancing_time,
        )
        # Should succeed on the second iteration after restart
        assert loop_result.result.success is True


class TestCleanupFailure:
    """Verify the cleanup-failure early-return path."""

    def test_cleanup_failure_returns_immediate_failure(self):
        """When cleanup agent fails, returns immediate failure."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_success,
            run_cleanup_return=(False, 1),
            is_shutting_down_calls=[False],
        )
        assert loop_result.immediate_result is not None
        assert loop_result.immediate_result.success is False
        assert loop_result.cleanup_agent_runs == 1


class TestGateFeedbackRetry:
    """Verify the gate-feedback → work-agent-retry loop."""

    def test_gate_feedback_retries_then_succeeds(self):
        """When gate gives feedback, work agent retries and succeeds."""
        invoke_calls = 0

        def invoke_fn(item, *, prompt, timeout, item_logger, model, cwd,
                      session_id, is_resume):
            nonlocal invoke_calls
            invoke_calls += 1
            return CopilotResult(
                work_item_id=item.id,
                success=True,
                output=f"Done iteration {invoke_calls}",
                attempt_count=1,
                session_id=f"sid-{invoke_calls}",
            )

        loop_result = _run_loop(
            invoke_fn=invoke_fn,
            gate_loop_side_effect=[
                # First gate run: feedback to retry
                _make_gate_loop_result(
                    gate_success=False,
                    feedback="Fix the tests",
                    gate_rejection_count=1,
                    gate_agent_runs=1,
                    session_id="gate-sid",
                    last_output_summary="summary",
                ),
                # Second gate run: success
                _make_gate_loop_result(gate_success=True, gate_agent_runs=2),
            ],
            is_shutting_down_calls=[False, False],
        )
        assert loop_result.gate_success is True
        assert invoke_calls == 2
        assert loop_result.result.success is True


class TestSdkInvariantCheck:
    """Verify the SDK invariant check break path."""

    def test_sdk_invariant_breaks_loop(self):
        """When check_sdk_invariant_fn returns True, loop breaks immediately."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_success,
            check_sdk_invariant_return=True,
            is_shutting_down_calls=[False],
        )
        # Should break before reaching cleanup or gate
        assert loop_result.immediate_result is None
        assert loop_result.gate_success is False


class TestProcessCrashDetection:
    """Verify process crash detection and retry paths."""

    def test_process_crash_with_retry(self):
        """When process crashes and retry is allowed, loop retries with feedback."""
        invoke_calls = 0

        def invoke_fn(item, *, prompt, timeout, item_logger, model, cwd,
                      session_id, is_resume):
            nonlocal invoke_calls
            invoke_calls += 1
            if invoke_calls == 1:
                return CopilotResult(
                    work_item_id=item.id,
                    success=False,
                    error="process died unexpectedly",
                    attempt_count=1,
                    session_id="crash-sid",
                    last_output_summary="partial output",
                )
            return CopilotResult(
                work_item_id=item.id,
                success=True,
                output="Done",
                attempt_count=1,
            )

        loop_result = _run_loop(
            invoke_fn=invoke_fn,
            maybe_retry_side_effect=[(True, "Try again"), (False, "")],
            is_shutting_down_calls=[False, False],
        )
        assert invoke_calls == 2
        assert loop_result.result.success is True

    def test_agent_failure_saves_session_state(self):
        """When agent fails with a session_id, it is saved for resume."""
        def invoke_fn(item, *, prompt, timeout, item_logger, model, cwd,
                      session_id, is_resume):
            return CopilotResult(
                work_item_id=item.id,
                success=False,
                error="something went wrong",
                attempt_count=1,
                session_id="saved-sid",
                last_output_summary="partial",
            )

        loop_result = _run_loop(
            invoke_fn=invoke_fn,
            is_shutting_down_calls=[False],
        )
        assert loop_result.result.success is False


class TestFailFastOutcome:
    """Verify fail-fast outcome handling."""

    def test_fail_fast_returns_immediate_result(self):
        """When work agent reports a fail-fast status and handler returns
        a result, it is returned immediately."""
        from pokepoke.types import WorkItemResult
        from pokepoke.work_agent_outcome import WorkAgentOutcome

        def invoke_fn(item, *, prompt, timeout, item_logger, model, cwd,
                      session_id, is_resume):
            return CopilotResult(
                work_item_id=item.id,
                success=True,
                output="blocked",
                attempt_count=1,
                work_agent_outcome=WorkAgentOutcome(
                    status="blocked", reason="Missing dependency"
                ),
            )

        ff_result = WorkItemResult(success=False, request_count=1,
                                   failure_reason="blocked")
        loop_result = _run_loop(
            invoke_fn=invoke_fn,
            handle_fail_fast_return=(ff_result, None),
            is_shutting_down_calls=[False],
        )
        assert loop_result.immediate_result is ff_result

    def test_fail_fast_too_large_calls_decompose(self):
        """When fail-fast returns None result but too_large context,
        the loop breaks after calling decompose."""
        from pokepoke.work_agent_outcome import WorkAgentOutcome

        def invoke_fn(item, *, prompt, timeout, item_logger, model, cwd,
                      session_id, is_resume):
            return CopilotResult(
                work_item_id=item.id,
                success=True,
                output="too large",
                attempt_count=1,
                work_agent_outcome=WorkAgentOutcome(
                    status="too_large",
                    reason="Item is too complex",
                    suggested_split=["part-a", "part-b"],
                ),
            )

        loop_result = _run_loop(
            invoke_fn=invoke_fn,
            handle_fail_fast_return=(None, "split context"),
            is_shutting_down_calls=[False],
        )
        # No immediate result (handler returned None), but loop broke
        assert loop_result.immediate_result is None


class TestBeadsItemClosed:
    """Verify the beads-item-already-closed shortcut."""

    def test_beads_item_closed_skips_cleanup_and_gate(self):
        """When beads item is already closed by the agent,
        cleanup and gate are skipped, gate_success is True."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_success,
            beads_closed=True,
            is_shutting_down_calls=[False],
        )
        assert loop_result.gate_success is True
        assert loop_result.cleanup_agent_runs == 0


class TestGateDisabled:
    """Verify gate-disabled config path."""

    def test_gate_disabled_skips_gate(self):
        """When gate_agent_enabled is False, gate is skipped and
        gate_success is set to True."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_success,
            global_config_overrides={"gate_agent_enabled": False},
            is_shutting_down_calls=[False],
        )
        assert loop_result.gate_success is True


class TestBranchVerificationError:
    """Verify branch verification error path."""

    def test_branch_error_returns_failure(self):
        """When verify_worktree_branch_fn returns an error,
        loop returns immediate failure."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_success,
            verify_branch_return="Branch mismatch: expected task-1",
            is_shutting_down_calls=[False],
        )
        assert loop_result.immediate_result is not None
        assert loop_result.immediate_result.success is False


class TestWorkAgentFailureWithRetry:
    """Verify work agent failure paths with and without retry."""

    def test_failure_with_retry_continues_loop(self):
        """When agent fails and maybe_retry returns True, loop continues."""
        invoke_calls = 0

        def invoke_fn(item, *, prompt, timeout, item_logger, model, cwd,
                      session_id, is_resume):
            nonlocal invoke_calls
            invoke_calls += 1
            if invoke_calls == 1:
                return CopilotResult(
                    work_item_id=item.id,
                    success=False,
                    error="flaky error",
                    attempt_count=1,
                )
            return CopilotResult(
                work_item_id=item.id,
                success=True,
                output="Done",
                attempt_count=1,
            )

        loop_result = _run_loop(
            invoke_fn=invoke_fn,
            maybe_retry_side_effect=[(True, "Retry please"), (False, "")],
            is_shutting_down_calls=[False, False],
        )
        assert invoke_calls == 2
        assert loop_result.result.success is True

    def test_failure_no_retry_breaks(self):
        """When agent fails and retry not allowed, loop breaks."""
        loop_result = _run_loop(
            invoke_fn=_invoke_copilot_failure,
            is_shutting_down_calls=[False],
        )
        assert loop_result.result.success is False
        assert loop_result.gate_success is False


class TestShutdownBehavior:
    """Verify the is_shutting_down exit path."""

    def test_immediate_shutdown_returns_default_result(self):
        """When is_shutting_down is True immediately, loop never executes."""
        loop_result = _run_loop(
            is_shutting_down_calls=[True],
        )
        # Loop body never ran — result is the default aborted result
        assert loop_result.result.success is False
        assert "shutdown" in loop_result.result.error.lower()
