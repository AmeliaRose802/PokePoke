"""Extended coverage tests for process_work_item in workflow.py.

Exercises critical paths that are under-tested: gate rejection cap,
assignment failure, worktree failure, copilot retry loops, fail-fast
outcomes, beads-item-closed shortcut, timeout restarts, finally-block
cleanup, cleanup agent failure, and worker context persistence.
"""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.orchestration.workflow import WorkItemConfig, process_work_item
from pokepoke.types import WorkItemResult
from pokepoke.types_agent import CopilotResult, GateAgentResult
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.work_agent_outcome import WorkAgentOutcome
from tests.fakes import FakeBeadsClient

# ---------------------------------------------------------------------------
# Module-level patch target prefix
# ---------------------------------------------------------------------------
_WF = "pokepoke.orchestration.workflow"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str = "test-ext-1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title=f"Item {item_id}",
        description="test description",
        status="open",
        priority=1,
        issue_type="task",
    )


def _make_config(
    *,
    max_gate_rejections: int = 5,
    gate_enabled: bool = False,
    max_retries: int = 3,
):
    cfg = Mock()
    cfg.max_gate_rejections_per_item = max_gate_rejections
    cfg.ai_backend.provider = "copilot"
    cfg.command_timeout = 300
    cfg.max_parallel_agents = 1
    cfg.max_copilot_failure_retries = max_retries
    cfg.gate_agent_enabled = gate_enabled
    return cfg


def _make_ui():
    ui = Mock()
    ui.agent_output_for.return_value = nullcontext()
    return ui


_SENTINEL = object()


def _base_patches(  # noqa: PLR0913
    *,
    config=None,
    setup_worktree_rv=_SENTINEL,
    invoke_results=None,
    cleanup_rv=(True, 0),
    gate_rv=None,
    is_shutting_down_seq=None,
    gate_rejection_count=0,
    is_beads_closed=False,
    assign_rv=True,
    verify_branch_rv=None,
    finalize_rv=True,
):
    """Return a dict of (target, kwargs) pairs for common patches.

    Caller enters them via an ExitStack or contextmanager.
    """
    if config is None:
        config = _make_config()
    if setup_worktree_rv is _SENTINEL:
        setup_worktree_rv = Path("C:/fake/worktree")
    if invoke_results is None:
        invoke_results = [
            CopilotResult(work_item_id="test-ext-1", success=True, attempt_count=1)
        ]
    if is_shutting_down_seq is None:
        is_shutting_down_seq = [False, True]
    if gate_rv is None:
        gate_rv = GateAgentResult(success=True, reason="ok")

    ui = _make_ui()

    patches = {
        "get_config": patch(f"{_WF}.get_config", return_value=config),
        "select_model": patch(f"{_WF}.select_model_for_item", return_value="test-model"),
        "get_assignment": patch(
            f"{_WF}.get_assignment_for_item",
            return_value=("test-model", "beads-item"),
        ),
        "terminal_ui": patch(f"{_WF}.terminal_ui.ui", ui),
        "setup_worktree": patch(
            f"{_WF}.setup_worktree", return_value=setup_worktree_rv
        ),
        "invoke_copilot": patch(
            f"{_WF}.invoke_copilot", side_effect=invoke_results
        ),
        "run_gate_agent": patch(f"{_WF}.run_gate_agent", return_value=gate_rv),
        "set_work_item_id": patch(f"{_WF}.set_current_work_item_id"),
        "set_repo_name": patch(f"{_WF}.set_current_repo_name"),
        "register_agent": patch(f"{_WF}.register_agent"),
        "unregister_agent": patch(f"{_WF}.unregister_agent"),
        "is_shutting_down": patch(
            f"{_WF}.is_shutting_down", side_effect=is_shutting_down_seq
        ),
        "get_agent_name": patch(f"{_WF}.get_agent_name", return_value="test-agent"),
        "verify_worktree_branch": patch(
            f"{_WF}.verify_worktree_branch", return_value=verify_branch_rv
        ),
        "gate_rejection_count": patch(
            "pokepoke.beads.beads_management.get_gate_rejection_count",
            return_value=gate_rejection_count,
        ),
        "build_prompt": patch(
            f"{_WF}.build_prompt_from_work_item", return_value="test prompt"
        ),
        "cleanup_timeout": patch(
            f"{_WF}.run_cleanup_with_timeout", return_value=cleanup_rv
        ),
        "get_worker_contexts": patch(
            f"{_WF}.get_worker_contexts", return_value=[]
        ),
        "format_worker_context": patch(
            f"{_WF}.format_worker_context_for_prompt", return_value=""
        ),
        "save_worker_context": patch(f"{_WF}.save_worker_context"),
        "build_resume_prompt": patch(
            f"{_WF}.build_resume_prompt", return_value="resume prompt"
        ),
        "assign_and_sync": patch(
            f"{_WF}.assign_and_sync_item", return_value=assign_rv
        ),
        "is_beads_closed": patch(
            "pokepoke.beads.reconciliation.is_beads_item_closed",
            return_value=is_beads_closed,
        ),
        "finalize": patch(
            f"{_WF}._finalize_item_result",
        ),
        "log_failure": patch(f"{_WF}._log_failure"),
        "log_commit_status": patch(f"{_WF}._log_commit_status"),
        "maybe_decompose": patch(f"{_WF}._maybe_decompose"),
        "maybe_retry_copilot": patch(f"{_WF}._maybe_retry_copilot"),
        "apply_gate_feedback": patch(f"{_WF}._apply_gate_feedback"),
        "extract_agent_stats": patch(
            f"{_WF}._extract_agent_stats", return_value=None
        ),
        "agent_type_context": patch(
            "pokepoke.stats.metrics_context.agent_type_context",
            return_value=nullcontext(),
        ),
        "time_sleep": patch(f"{_WF}.time.sleep"),
        "session_cleanup": patch(
            "pokepoke.orchestration.work_item_session.WorkItemSession.cleanup_on_failure"
        ),
        "decompose_should": patch(
            "pokepoke.agents.decomposition_agent.should_decompose",
            return_value=False,
        ),
    }
    return patches, ui


class _PatchCtx:
    """Helper to enter all patches and provide access to mock objects."""

    def __init__(self, patches_dict, ui, finalize_rv=True):
        self._patches = patches_dict
        self.ui = ui
        self._finalize_rv = finalize_rv
        self.mocks = {}

    def __enter__(self):
        for key, p in self._patches.items():
            self.mocks[key] = p.start()
        # Configure finalize to return a default result
        fin_mock = self.mocks.get("finalize")
        if fin_mock is not None:
            fin_mock.return_value = (
                WorkItemResult(success=self._finalize_rv, request_count=1),
                self._finalize_rv,
            )
        return self

    def __exit__(self, *args):
        for p in self._patches.values():
            p.stop()


def _run(item=None, interactive=False, beads_client=None, timeout_hours=0,
         max_timeout_restarts=3, **patch_kwargs):
    """Run process_work_item with a full set of patches and return result + ctx."""
    if item is None:
        item = _make_item()
    patches, ui = _base_patches(**patch_kwargs)
    finalize_rv = patch_kwargs.get("finalize_rv", True)
    ctx = _PatchCtx(patches, ui, finalize_rv=finalize_rv)
    wi_config = WorkItemConfig(
        timeout_hours=timeout_hours,
        max_timeout_restarts=max_timeout_restarts,
        beads_client=beads_client,
    )
    with ctx:
        result = process_work_item(
            item,
            interactive=interactive,
            config=wi_config,
        )
    return result, ctx


# ===================================================================
# Tests
# ===================================================================


class TestGateRejectionCapExceeded:
    """Gate rejection cap pre-check moved to selection phase.

    process_work_item no longer checks the cap on entry — items at/above the
    cap are filtered out in _filter_available / select_multiple_items before
    being submitted to process_work_item.  See
    test_work_item_selection_coverage.py for selection-level cap tests.
    """

    def test_item_at_cap_proceeds_in_workflow(self):
        """Items reaching the cap are filtered at selection, not in workflow."""
        item = _make_item()
        # Even with metadata showing cap reached, workflow proceeds to assign
        item = BeadsWorkItem(
            id=item.id, title=item.title, description=item.description,
            status=item.status, priority=item.priority, issue_type=item.issue_type,
            metadata={"gate_rejection_count": 5},
        )
        _result, ctx = _run(
            item=item,
            config=_make_config(max_gate_rejections=3, gate_enabled=False),
            is_shutting_down_seq=[False, False],
        )
        # Item was processed (assign was called), not rejected at cap
        ctx.mocks["assign_and_sync"].assert_called_once()

    def test_gate_rejection_count_read_from_metadata(self):
        """Workflow reads initial gate_rejection_count from item.metadata."""
        item = BeadsWorkItem(
            id="test-ext-1", title="Item test-ext-1", description="test",
            status="open", priority=1, issue_type="task",
            metadata={"gate_rejection_count": 2},
        )
        # With assign failing, we can verify the item was processed
        result, ctx = _run(item=item, assign_rv=False)
        assert result.success is False
        # Failure is from assign, not cap check
        ctx.mocks["setup_worktree"].assert_not_called()


class TestAssignmentFailure:
    """When assign returns False, should return fail result."""

    def test_assign_false_returns_failure(self):
        item = _make_item()

        result, ctx = _run(item=item, assign_rv=False)

        assert result.success is False
        ctx.mocks["invoke_copilot"].assert_not_called()

    def test_assign_false_with_beads_client(self):
        item = _make_item()
        client = FakeBeadsClient()
        # Don't add item → assign will return False
        result, _ = _run(item=item, beads_client=client)

        assert result.success is False


class TestWorktreeCreationFailure:
    """When setup_worktree returns None, should return fail result."""

    def test_worktree_none_returns_failure(self):
        item = _make_item()

        result, ctx = _run(item=item, setup_worktree_rv=None)

        assert result.success is False
        ctx.mocks["invoke_copilot"].assert_not_called()


class TestCopilotSuccessGateDisabled:
    """Happy path: copilot succeeds, gate is disabled."""

    def test_success_no_gate(self):
        item = _make_item()

        result, ctx = _run(
            item=item,
            config=_make_config(gate_enabled=False),
            invoke_results=[
                CopilotResult(
                    work_item_id=item.id, success=True, attempt_count=1
                )
            ],
            is_shutting_down_seq=[False, False],
        )

        assert result.success is True
        ctx.mocks["invoke_copilot"].assert_called_once()
        ctx.mocks["run_gate_agent"].assert_not_called()


class TestCopilotFailureWithRetry:
    """First attempt fails, retry succeeds."""

    def test_retry_succeeds(self):
        item = _make_item()
        fail_result = CopilotResult(
            work_item_id=item.id, success=False, error="Transient error",
            attempt_count=1,
        )
        ok_result = CopilotResult(
            work_item_id=item.id, success=True, attempt_count=1,
        )

        patches, ui = _base_patches(
            config=_make_config(max_retries=3, gate_enabled=False),
            invoke_results=[fail_result, ok_result],
            # Loop runs twice: first fail → retry, second succeed → break
            is_shutting_down_seq=[False, False, False],
        )
        ctx = _PatchCtx(patches, ui)
        with ctx:
            # _maybe_retry_copilot must signal retry on first call, then let through
            ctx.mocks["maybe_retry_copilot"].return_value = (True, "retry feedback")
            ctx.mocks["apply_gate_feedback"].return_value = (["retry feedback"], 2)

            result = process_work_item(item, interactive=False)

        assert result.success is True
        assert ctx.mocks["invoke_copilot"].call_count == 2


class TestCopilotFailureExhausted:
    """All retries fail → break out of loop."""

    def test_all_retries_fail(self):
        item = _make_item()
        fail_result = CopilotResult(
            work_item_id=item.id, success=False,
            error="Persistent failure", attempt_count=1,
        )

        patches, ui = _base_patches(
            config=_make_config(max_retries=2, gate_enabled=False),
            invoke_results=[fail_result],
            is_shutting_down_seq=[False, False],
        )
        ctx = _PatchCtx(patches, ui, finalize_rv=False)
        with ctx:
            ctx.mocks["maybe_retry_copilot"].return_value = (False, "")

            process_work_item(item, interactive=False)

        # finalize_rv=False → WorkItemResult(success=False)
        assert ctx.mocks["finalize"].called


class TestFailFastOutcomes:
    """Work agent returns blocked/needs_clarification → skip gate."""

    @pytest.mark.parametrize("status", ["blocked", "needs_clarification", "too_large"])
    def test_fail_fast_status_breaks(self, status):
        item = _make_item()
        outcome = WorkAgentOutcome(status=status, reason=f"Item is {status}")
        copilot_result = CopilotResult(
            work_item_id=item.id, success=True, attempt_count=1,
            work_agent_outcome=outcome,
        )
        client = FakeBeadsClient()
        client.add_item(item)

        patches, ui = _base_patches(
            config=_make_config(gate_enabled=True),
            invoke_results=[copilot_result],
            is_shutting_down_seq=[False, False],
        )
        ctx = _PatchCtx(patches, ui, finalize_rv=False)
        with ctx:
            process_work_item(item, interactive=False, config=WorkItemConfig(beads_client=client))

        # Gate should NOT be called for fail-fast outcomes
        ctx.mocks["run_gate_agent"].assert_not_called()
        # Comment should be added about the status
        assert client.call_count("add_comment") >= 1


class TestBeadsItemAlreadyClosed:
    """Agent self-merged, beads item is closed → skip gate."""

    def test_item_closed_skips_gate(self):
        item = _make_item()
        copilot_result = CopilotResult(
            work_item_id=item.id, success=True, attempt_count=1,
        )

        result, ctx = _run(
            item=item,
            config=_make_config(gate_enabled=True),
            invoke_results=[copilot_result],
            is_shutting_down_seq=[False, False],
            is_beads_closed=True,
        )

        assert result.success is True
        ctx.mocks["run_gate_agent"].assert_not_called()


class TestTimeoutRestart:
    """Timeout hit, restart succeeds within max_timeout_restarts."""

    def test_timeout_then_succeed(self):
        item = _make_item()
        ok_result = CopilotResult(
            work_item_id=item.id, success=True, attempt_count=1,
        )

        call_count = 0

        def time_side_effect():
            nonlocal call_count
            call_count += 1
            # First time.time() → start_time = 0
            # Second → elapsed check: 4000 > 3.6 → restart 1
            # Third → reset start_time = 4001
            # Fourth → elapsed check: 4001 - 4001 = 0, no timeout → proceed
            if call_count == 1:
                return 0.0
            if call_count == 2:
                return 4000.0
            return 4001.0

        patches, ui = _base_patches(
            config=_make_config(gate_enabled=False),
            invoke_results=[ok_result],
            is_shutting_down_seq=[False, False, False],
        )
        with _PatchCtx(patches, ui), \
             patch(f"{_WF}.time.time", side_effect=time_side_effect):
            result = process_work_item(
                item,
                interactive=False,
                config=WorkItemConfig(timeout_hours=1.0, max_timeout_restarts=3),
            )

        assert result.success is True


class TestTimeoutRestartExhausted:
    """Exceeds max_timeout_restarts → fail."""

    def test_max_restarts_exceeded(self):
        item = _make_item()

        call_count = 0

        def advancing_time():
            nonlocal call_count
            call_count += 1
            # Each call returns 10000*count so elapsed always exceeds timeout
            return float(call_count * 10000)

        # Copilot fails each time, but retry=True keeps the loop going
        fail = CopilotResult(
            work_item_id=item.id, success=False,
            error="Transient", attempt_count=1,
        )

        patches, ui = _base_patches(
            config=_make_config(gate_enabled=False, max_retries=10),
            invoke_results=[fail, fail, fail],
            is_shutting_down_seq=[False] * 15,
        )
        ctx = _PatchCtx(patches, ui, finalize_rv=False)
        with ctx:
            # Each copilot failure triggers a retry (loop continues)
            ctx.mocks["maybe_retry_copilot"].return_value = (True, "retry")
            ctx.mocks["apply_gate_feedback"].return_value = (["retry"], 2)

            with patch(f"{_WF}.time.time", side_effect=advancing_time):
                result = process_work_item(
                    item,
                    interactive=False,
                    config=WorkItemConfig(timeout_hours=0.001, max_timeout_restarts=2),
                )

        assert result.success is False
        assert "timeout" in (result.failure_reason or "").lower()


class TestFinallyBlockCleanup:
    """Session cleanup_on_failure called on exception."""

    def test_cleanup_called_on_unexpected_exception(self):
        item = _make_item()

        patches, ui = _base_patches(
            config=_make_config(),
            invoke_results=[],
            is_shutting_down_seq=[False, False],
        )
        ctx = _PatchCtx(patches, ui)
        with ctx:
            # Force an exception inside the loop by making invoke raise
            ctx.mocks["invoke_copilot"].side_effect = RuntimeError("boom")

            with pytest.raises(RuntimeError, match="boom"):
                process_work_item(item, interactive=False)

            ctx.mocks["session_cleanup"].assert_called_once()

    def test_no_cleanup_when_shutting_down(self):
        item = _make_item()

        patches, ui = _base_patches(
            config=_make_config(),
            invoke_results=[],
            # Immediately shutting down — never enters loop
            is_shutting_down_seq=[True],
        )
        ctx = _PatchCtx(patches, ui)
        with ctx:
            # Make is_shutting_down return True for the finally check too
            ctx.mocks["is_shutting_down"].side_effect = None
            ctx.mocks["is_shutting_down"].return_value = True

            process_work_item(item, interactive=False)

        # cleanup_on_failure should NOT be called when shutting down
        ctx.mocks["session_cleanup"].assert_not_called()


class TestCleanupAgentFailure:
    """Cleanup returns False → fail result."""

    def test_cleanup_failure_returns_fail(self):
        item = _make_item()
        ok_result = CopilotResult(
            work_item_id=item.id, success=True, attempt_count=1,
        )

        result, _ctx = _run(
            item=item,
            config=_make_config(gate_enabled=True),
            invoke_results=[ok_result],
            cleanup_rv=(False, 1),
            is_shutting_down_seq=[False, False],
        )

        assert result.success is False
        assert "cleanup" in (result.failure_reason or "").lower()


class TestWorkerContextSavedOnFailure:
    """save_worker_context is called when the attempt fails."""

    def test_save_context_called(self):
        item = _make_item()
        fail_result = CopilotResult(
            work_item_id=item.id, success=False,
            error="Something went wrong", attempt_count=1,
        )

        patches, ui = _base_patches(
            config=_make_config(max_retries=0),
            invoke_results=[fail_result],
            is_shutting_down_seq=[False, False],
        )
        ctx = _PatchCtx(patches, ui, finalize_rv=False)
        with ctx:
            ctx.mocks["maybe_retry_copilot"].return_value = (False, "")

            result = process_work_item(item, interactive=False)

        assert result.success is False
        ctx.mocks["save_worker_context"].assert_called_once()
        call_kwargs = ctx.mocks["save_worker_context"].call_args
        assert call_kwargs[1].get("item_id", call_kwargs[0][0] if call_kwargs[0] else None) == item.id or item.id in str(call_kwargs)

    def test_no_save_on_success(self):
        item = _make_item()
        ok_result = CopilotResult(
            work_item_id=item.id, success=True, attempt_count=1,
        )

        _, ctx = _run(
            item=item,
            config=_make_config(gate_enabled=False),
            invoke_results=[ok_result],
            is_shutting_down_seq=[False, False],
        )

        ctx.mocks["save_worker_context"].assert_not_called()


class TestUnregisterAgentAlwaysCalled:
    """unregister_agent is called in finally block regardless of outcome."""

    def test_unregister_on_success(self):
        _, ctx = _run()
        ctx.mocks["unregister_agent"].assert_called_once()

    def test_unregister_on_failure(self):
        _, ctx = _run(assign_rv=False)
        ctx.mocks["unregister_agent"].assert_called_once()

    def test_unregister_on_exception(self):
        item = _make_item()
        patches, ui = _base_patches(
            invoke_results=[],
            # Need: 1 for while-loop entry, 1 for finally-block check
            is_shutting_down_seq=[False, False],
        )
        ctx = _PatchCtx(patches, ui)
        with ctx:
            ctx.mocks["invoke_copilot"].side_effect = RuntimeError("crash")
            with pytest.raises(RuntimeError):
                process_work_item(item, interactive=False)
            ctx.mocks["unregister_agent"].assert_called_once()


class TestVerifyWorktreeBranchError:
    """verify_worktree_branch returns an error string → fail."""

    def test_branch_error_returns_failure(self):
        item = _make_item()
        ok_result = CopilotResult(
            work_item_id=item.id, success=True, attempt_count=1,
        )

        result, ctx = _run(
            item=item,
            invoke_results=[ok_result],
            verify_branch_rv="Wrong branch: expected task/test-ext-1",
            is_shutting_down_seq=[False, False],
        )

        assert result.success is False
        assert "branch" in (result.failure_reason or "").lower()
        ctx.mocks["invoke_copilot"].assert_not_called()
