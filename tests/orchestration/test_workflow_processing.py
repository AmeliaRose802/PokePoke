"""Unit tests for workflow work item processing.

This module tests work item processing logic including:
- Processing lifecycle and orchestration
- Copilot CLI invocation and retries
- Gate agent validation and rejection handling
- Timeout and restart behavior
- Concurrent agent coordination
"""

from unittest.mock import patch

import pytest

from pokepoke.orchestration.workflow import WorkItemConfig, process_work_item
from pokepoke.types_agent import CopilotResult, GateAgentResult
from pokepoke.types_stats import AgentStats
from tests.orchestration.conftest import (
    PATCH_MODEL_CONFIG,
    PATCH_WF_ADD_COMMENT,
    PATCH_WF_IS_SHUTTING_DOWN,
    PATCH_WF_SELECT_MODEL,
    make_process_item_mocks,
    make_work_item,
)


@pytest.fixture(autouse=True)
def _mock_decomposition():
    """Prevent decomposition from invoking real SDK during tests."""
    with patch("pokepoke.agents.decomposition_agent.should_decompose", return_value=False):
        yield


class TestProcessWorkItem:
    """Test process_work_item function."""

    def test_skip_in_interactive_mode(self) -> None:
        """Test skipping item in interactive mode."""
        item = make_work_item()

        with make_process_item_mocks(include_config=True) as mocks:
            mocks['input'].return_value = 'n'
            with patch(PATCH_MODEL_CONFIG) as mock_model_config:
                mock_model_config.return_value.models.candidate_models = ["gemini-3-pro"]
                mock_model_config.return_value.models.default = "gemini-3-pro"

                result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None
            assert result.cleanup_agent_runs == 0
            mocks['setup'].assert_not_called()

    def test_worktree_setup_fails(self) -> None:
        """Test when worktree setup fails, process returns failure."""
        item = make_work_item()

        with make_process_item_mocks(
            worktree_path=None, include_session_cleanup=True,
        ):
            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None
            assert result.cleanup_agent_runs == 0

    def test_shutdown_before_first_iteration_does_not_crash(self) -> None:
        """Shutdown before first loop iteration should not raise UnboundLocalError."""
        item = make_work_item()

        with make_process_item_mocks(
            include_session_cleanup=True, include_cleanup_worktree=True,
        ) as mocks:
            with patch(PATCH_WF_IS_SHUTTING_DOWN, return_value=True), \
                 patch(PATCH_WF_SELECT_MODEL, return_value="test-model"):
                result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            # Stats are now tracked even on failure/shutdown
            assert result.stats is not None
            assert result.cleanup_agent_runs == 0
            assert result.gate_agent_runs == 0
            assert result.model_completion is not None
            mocks['invoke'].assert_not_called()
            # Worktree should be preserved on shutdown — cleanup_on_failure must NOT run
            mocks['session_cleanup'].assert_not_called()

    def test_no_changes_made(self) -> None:
        """Test when Copilot makes no changes (no uncommitted and no commits ahead)."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0, include_handoff=True,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.request_count == 1
            # Cleanup is called even with no changes (it just exits early)
            mocks['cleanup_timeout'].assert_called_once()

    def test_changes_already_committed(self) -> None:
        """Test when Copilot committed changes (clean tree but commits ahead)."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=2, include_handoff=True,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.request_count == 1
            # Verify has_commits_ahead was called (distinguishes from "no changes")
            mocks['commits_ahead'].assert_called_once()

    def test_copilot_failure(self) -> None:
        """Test when Copilot CLI fails (no retries configured)."""
        item = make_work_item()

        with make_process_item_mocks(
            copilot_success=False, uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 1
            mocks['session_cleanup'].assert_called()

    def test_copilot_failure_retries_exhausted(self) -> None:
        """Test that all retries are attempted when Copilot fails, then item fails."""
        item = make_work_item()

        with make_process_item_mocks(
            copilot_success=False, uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is False
            # 1 initial + 2 retries = 3 total invocations, each with attempt_count=1
            assert result.request_count == 3
            assert mocks['invoke'].call_count == 3
            mocks['session_cleanup'].assert_called()

    def test_copilot_failure_retried_successfully(self) -> None:
        """Test that a failed Copilot attempt is retried and can succeed."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_config=True, include_handoff=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            # First attempt fails, second succeeds
            mocks['invoke'].side_effect = [
                CopilotResult(
                    work_item_id="task-1", success=False,
                    error="Tests failed", attempt_count=1,
            session_id="test-session",
        ),
                CopilotResult(
                    work_item_id="task-1", success=True,
                    output="Done", attempt_count=1,
            session_id="test-session",
        ),
            ]

            result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.request_count == 2
            assert mocks['invoke'].call_count == 2
            # Description must NOT be mutated — feedback goes via prompt
            assert item.description == ""

    def test_copilot_failure_no_retry_when_rate_limited(self) -> None:
        """Test that rate-limited failures are not retried."""
        item = make_work_item()

        with make_process_item_mocks(
            copilot_success=False, uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            mocks['invoke'].return_value = CopilotResult(
                work_item_id="task-1", success=False,
                error="Rate limit exceeded", attempt_count=1,
                is_rate_limited=True,
            session_id="test-session",
        )

            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 1  # No retry on rate limit
            assert mocks['invoke'].call_count == 1

    def test_process_crash_still_runs_gate_agent(self) -> None:
        """Test that gate agent runs even when CLI process crashed on earlier attempt.

        Bug fix: Previously, process_crashed_this_session flag would permanently skip gate
        even if retry succeeded. Now gate always runs if work agent eventually succeeds.
        """
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            include_handoff=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            # First attempt: process crashes
            # Second attempt: succeeds
            mocks['invoke'].side_effect = [
                CopilotResult(
                    work_item_id="task-1", success=False,
                    error="Process died: consecutive ping failures or output timeout",
                    attempt_count=1,
            session_id="test-session",
        ),
                CopilotResult(
                    work_item_id="task-1", success=True,
                    output="Fixed on retry", attempt_count=1,
            session_id="test-session",
        ),
            ]

            result = process_work_item(item, interactive=True)

            # Should succeed (retry worked)
            assert result.success is True
            assert result.request_count == 2
            # Gate agent SHOULD have been called (work agent succeeded, gate must verify)
            assert mocks['gate'].call_count == 1

    def test_sdk_exception_crash_still_runs_gate_agent(self) -> None:
        """Test that gate agent runs for SDK exceptions with 'exited unexpectedly' pattern.

        Bug fix: Previously, process crash detection would permanently skip gate.
        Now gate runs if work agent eventually succeeds, regardless of earlier crashes.
        """
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            include_handoff=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            # First attempt: SDK exception with CLI process crash
            # Second attempt: succeeds
            mocks['invoke'].side_effect = [
                CopilotResult(
                    work_item_id="task-1", success=False,
                    error="SDK exception: CLI process exited unexpectedly",
                    attempt_count=1,
            session_id="test-session",
        ),
                CopilotResult(
                    work_item_id="task-1", success=True,
                    output="Fixed on retry", attempt_count=1,
            session_id="test-session",
        ),
            ]

            result = process_work_item(item, interactive=True)

            # Should succeed (retry worked)
            assert result.success is True
            assert result.request_count == 2
            # Gate agent SHOULD have been called (work agent succeeded, gate must verify)
            assert mocks['gate'].call_count == 1

    def test_gate_agent_retry_loop(self) -> None:
        """Test gate agent rejection triggers retry loop."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_handoff=True, include_cleanup_worktree=True,
        ) as mocks:
            # Gate agent fails first time, passes second time
            mocks['gate'].side_effect = [
                GateAgentResult(success=False, reason="Tests failed"),
                GateAgentResult(success=True, reason="All tests pass"),
            ]
            # Two work agent invocations
            mocks['invoke'].side_effect = [
                CopilotResult(work_item_id="task-1", success=True, output="Try 1", attempt_count=1,
            session_id="test-session",
        ),
                CopilotResult(work_item_id="task-1", success=True, output="Try 2", attempt_count=1,
            session_id="test-session",
        ),
            ]
            with patch(PATCH_WF_ADD_COMMENT) as mock_add_comment:
                result = process_work_item(item, interactive=True)

                assert result.success is True
                assert result.request_count == 2  # Two invocations
                mock_add_comment.assert_called_once()  # Comment added for gate rejection
                assert mocks['gate'].call_count == 2

            # Description must NOT be mutated — feedback goes via prompt
            assert item.description == ""

    def test_gate_agent_stats_aggregation(self) -> None:
        """Test gate agent stats are aggregated into totals."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_handoff=True, include_cleanup_worktree=True,
        ) as mocks:
            # Gate agent returns stats
            gate_stats = AgentStats(
                wall_duration=5.0, api_duration=2.0,
                input_tokens=50, output_tokens=25, premium_requests=1,
            )
            mocks['gate'].return_value = GateAgentResult(
                success=True, reason="Pass", stats=gate_stats,
            )

            work_stats = AgentStats(
                wall_duration=10.0, api_duration=5.0,
                input_tokens=100, output_tokens=50, premium_requests=2,
            )
            mocks['invoke'].return_value = CopilotResult(
                work_item_id="task-1", success=True, output="Completed",
                attempt_count=1, stats=work_stats,
            session_id="test-session",
        )

            with patch(PATCH_WF_ADD_COMMENT):
                result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.stats is not None
            # Gate agent stats should NOT be aggregated into work agent stats (yja0 fix)
            assert result.stats.wall_duration == 10.0  # Only work agent stats
            assert result.stats.input_tokens == 100  # Only work agent tokens
            assert result.gate_agent_runs == 1  # Gate agent ran once

    def test_cleanup_failure_returns_stats(self) -> None:
        """Test that cleanup failure returns accumulated stats."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_session_cleanup=True, include_cleanup_worktree=True,
        ) as mocks:
            work_stats = AgentStats(
                wall_duration=10.0, api_duration=5.0,
                input_tokens=100, output_tokens=50,
            )
            mocks['invoke'].return_value = CopilotResult(
                work_item_id="task-1", success=True, output="Completed",
                attempt_count=1, stats=work_stats,
            session_id="test-session",
        )
            mocks['cleanup_timeout'].return_value = (False, 2)  # Cleanup fails

            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.cleanup_agent_runs == 2
            assert result.stats is not None  # Stats should be returned even on failure
            assert result.stats.wall_duration == 10.0

    def test_timeout_restarts_limited(self) -> None:
        """Test that repeated timeouts are bounded by max_timeout_restarts."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0,
            include_handoff=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            # Use a very short timeout (0.001 hours = 3.6s) so timeout fires reliably
            # Return monotonically increasing values; each call 5s apart ensures timeout
            call_count = [0]
            def time_side_effect():
                call_count[0] += 1
                return call_count[0] * 5.0
            mocks['time'].side_effect = time_side_effect
            mocks['gate'].return_value = GateAgentResult(success=False, reason="Rejected")

            with patch(PATCH_WF_SELECT_MODEL, return_value="test-model"), \
                 patch(PATCH_WF_ADD_COMMENT), \
                 patch('time.sleep'):
                result = process_work_item(
                    item, interactive=True,
                    config=WorkItemConfig(timeout_hours=0.001, max_timeout_restarts=2),
                )

            assert result.success is False
            # Worktree is preserved on failure (not cleaned up)
            mocks['cleanup_wt'].assert_not_called()

    def test_timeout_restart_then_success(self) -> None:
        """Test that a timeout restart followed by success works correctly."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0, include_handoff=True,
        ) as mocks:
            # First iteration: past timeout. After restart, within timeout.
            call_count = 0
            def time_side_effect():
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    # Initial start_time and first elapsed check: past timeout
                    return 99999
                # After restart: well within timeout
                return 0

            mocks['time'].side_effect = time_side_effect

            result = process_work_item(
                item, interactive=True,
                config=WorkItemConfig(max_timeout_restarts=3),
            )

            assert result.success is True
            mocks['invoke'].assert_called_once()

    def test_timeout_backoff_escalates(self) -> None:
        """Test that backoff delay doubles on consecutive timeouts (30→60→120)."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0,
            include_handoff=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            call_count = [0]
            def time_side_effect():
                call_count[0] += 1
                return call_count[0] * 5.0
            mocks['time'].side_effect = time_side_effect
            mocks['gate'].return_value = GateAgentResult(success=False, reason="Rejected")

            with patch(PATCH_WF_SELECT_MODEL, return_value="test-model"), \
                 patch(PATCH_WF_ADD_COMMENT), \
                 patch('time.sleep') as mock_sleep:
                result = process_work_item(
                    item, interactive=True,
                    config=WorkItemConfig(timeout_hours=0.001, max_timeout_restarts=3),
                )

            assert result.success is False
            # Should have slept with escalating backoff: 30, 60, 120
            sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
            assert sleep_calls[:3] == [30, 60, 120]

    def test_timeout_backoff_caps_at_max(self) -> None:
        """Test that backoff delay caps at 240 seconds."""
        from pokepoke.orchestration.workflow import _BACKOFF_MAX_SECONDS

        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0,
            include_handoff=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            include_config=True,
        ) as mocks:
            mocks['config'].return_value.max_gate_rejections_per_item = 10
            call_count = [0]
            def time_side_effect():
                call_count[0] += 1
                return call_count[0] * 5.0
            mocks['time'].side_effect = time_side_effect
            mocks['gate'].return_value = GateAgentResult(success=False, reason="Rejected")

            with patch(PATCH_WF_SELECT_MODEL, return_value="test-model"), \
                 patch(PATCH_WF_ADD_COMMENT), \
                 patch('time.sleep') as mock_sleep:
                # Allow enough restarts to hit the cap: 30→60→120→240→240
                result = process_work_item(
                    item, interactive=True,
                    config=WorkItemConfig(timeout_hours=0.001, max_timeout_restarts=5),
                )

            assert result.success is False
            sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
            # 30, 60, 120, 240, 240 — capped at max
            assert sleep_calls == [30, 60, 120, 240, 240]
            assert all(d <= _BACKOFF_MAX_SECONDS for d in sleep_calls)

    def test_timeout_backoff_resets_on_success(self) -> None:
        """Test that backoff resets to base after gate success."""
        from pokepoke.orchestration.workflow import _BACKOFF_BASE_SECONDS

        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0, include_handoff=True,
        ) as mocks:
            restarted = [False]
            counter = [0]

            def sleep_side_effect(seconds):
                restarted[0] = True
                counter[0] = 0

            def time_side_effect():
                counter[0] += 1
                if restarted[0]:
                    return 500000.0  # constant after restart → elapsed = 0
                return counter[0] * 100.0  # increasing → elapsed grows

            mocks['time'].side_effect = time_side_effect

            with patch('time.sleep') as mock_sleep:
                mock_sleep.side_effect = sleep_side_effect
                result = process_work_item(
                    item, interactive=True,
                    config=WorkItemConfig(timeout_hours=0.001, max_timeout_restarts=3),
                )

            assert result.success is True
            mock_sleep.assert_called_once_with(_BACKOFF_BASE_SECONDS)


class TestProcessWorkItemCoordination:
    """Tests for concurrent-agent coordination paths in process_work_item."""

    def test_assign_fails_race_condition(self) -> None:
        """When assign_and_sync_item returns False (another agent already claimed the item),
        process_work_item must return (False, 0, ...) without creating a worktree."""
        item = make_work_item(id="task-race", title="Race Task")

        with make_process_item_mocks(assign_ok=False) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None
            mocks['setup'].assert_not_called()

    def test_worktree_lock_timeout(self) -> None:
        """When create_worktree times out (another agent holds the lock),
        process_work_item must return (False, 0, ...) without crashing.

        The lock is now acquired inside create_worktree via with_worktree_lock,
        not as a wrapper around the entire setup block.

        setup_worktree catches exceptions and returns None, so we simulate
        that behavior here by returning None (as if the lock timeout happened
        and setup_worktree caught the exception).
        """
        item = make_work_item(id="task-lock", title="Lock Task")

        with make_process_item_mocks(
            worktree_path=None, include_session_cleanup=True,
        ):
            result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None

    def test_worktree_failure_triggers_unassign(self) -> None:
        """When worktree creation fails after a successful claim,
        process_work_item must run session cleanup so the item is unassigned."""
        item = make_work_item(id="task-wt-fail", title="Worktree Fail Task")

        with make_process_item_mocks(
            worktree_path=None, include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            mocks['session_cleanup'].assert_called_once()


class TestWorkAgentOutcomeFailFast:
    """Tests for fail-fast behavior when work agent returns non-completion outcomes."""

    @pytest.mark.asyncio
    async def test_blocked_outcome_breaks_loop(self):
        """When work agent returns 'blocked', the workflow breaks early."""
        from pokepoke.orchestration.workflow import _FAIL_FAST_STATUSES
        from pokepoke.work_agent_outcome import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="blocked", reason="Missing dependency")
        assert outcome.status in _FAIL_FAST_STATUSES

    @pytest.mark.asyncio
    async def test_too_large_outcome_breaks_loop(self):
        from pokepoke.orchestration.workflow import _FAIL_FAST_STATUSES
        from pokepoke.work_agent_outcome import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="too_large", reason="Too many files", suggested_split=["a", "b"])
        assert outcome.status in _FAIL_FAST_STATUSES

    @pytest.mark.asyncio
    async def test_needs_clarification_breaks_loop(self):
        from pokepoke.orchestration.workflow import _FAIL_FAST_STATUSES
        from pokepoke.work_agent_outcome import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="needs_clarification", reason="Unclear requirements")
        assert outcome.status in _FAIL_FAST_STATUSES

    @pytest.mark.asyncio
    async def test_completed_not_in_fail_fast(self):
        from pokepoke.orchestration.workflow import _FAIL_FAST_STATUSES
        assert "completed" not in _FAIL_FAST_STATUSES

    @pytest.mark.asyncio
    async def test_fail_fast_statuses_is_frozen(self):
        from pokepoke.orchestration.workflow import _FAIL_FAST_STATUSES
        assert isinstance(_FAIL_FAST_STATUSES, frozenset)
