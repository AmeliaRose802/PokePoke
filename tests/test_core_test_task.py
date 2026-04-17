"""Tests for pokepoke.constants module.

Verifies that named constants are correctly defined with expected types
and reasonable value ranges.
"""

import pokepoke.constants as c


class TestPreflightConstants:
    """Verify preflight health-check constants."""

    def test_default_min_disk_space(self) -> None:
        assert isinstance(c.DEFAULT_MIN_DISK_SPACE_GB, float)
        assert c.DEFAULT_MIN_DISK_SPACE_GB > 0

    def test_min_disk_space_below_default(self) -> None:
        assert c.MIN_DISK_SPACE_GB <= c.DEFAULT_MIN_DISK_SPACE_GB

    def test_default_lock_timeout(self) -> None:
        assert c.DEFAULT_LOCK_TIMEOUT_SECONDS > 0

    def test_min_lock_timeout_below_default(self) -> None:
        assert c.MIN_LOCK_TIMEOUT_SECONDS <= c.DEFAULT_LOCK_TIMEOUT_SECONDS

    def test_default_worktree_test_timeout(self) -> None:
        assert c.DEFAULT_WORKTREE_TEST_TIMEOUT > 0

    def test_min_worktree_timeout_below_default(self) -> None:
        assert c.MIN_WORKTREE_TEST_TIMEOUT <= c.DEFAULT_WORKTREE_TEST_TIMEOUT

    def test_default_max_orphan_worktrees(self) -> None:
        assert isinstance(c.DEFAULT_MAX_ORPHAN_WORKTREES, int)
        assert c.DEFAULT_MAX_ORPHAN_WORKTREES >= 0

    def test_default_git_operation_timeout(self) -> None:
        assert c.DEFAULT_GIT_OPERATION_TIMEOUT > 0

    def test_default_max_repair_attempts(self) -> None:
        assert isinstance(c.DEFAULT_MAX_REPAIR_ATTEMPTS, int)
        assert c.DEFAULT_MAX_REPAIR_ATTEMPTS >= c.MIN_REPAIR_ATTEMPTS


class TestPerformanceThresholdConstants:
    """Verify performance threshold constants."""

    def test_merge_queue_depth_positive(self) -> None:
        assert c.DEFAULT_MAX_MERGE_QUEUE_DEPTH >= c.MIN_MERGE_QUEUE_DEPTH

    def test_lock_wait_seconds(self) -> None:
        assert c.DEFAULT_MAX_LOCK_WAIT_SECONDS >= c.MIN_LOCK_WAIT_SECONDS

    def test_iteration_seconds(self) -> None:
        assert c.DEFAULT_MAX_ITERATION_SECONDS >= c.MIN_ITERATION_SECONDS

    def test_min_memory_mb(self) -> None:
        assert c.DEFAULT_MIN_MEMORY_MB >= c.MIN_MEMORY_MB

    def test_min_success_rate_bounded(self) -> None:
        assert 0.0 <= c.DEFAULT_MIN_SUCCESS_RATE <= 1.0


class TestOrchestrationConstants:
    """Verify orchestration session constants."""

    def test_max_parallel_agents(self) -> None:
        assert c.DEFAULT_MAX_PARALLEL_AGENTS >= c.MIN_MAX_PARALLEL_AGENTS

    def test_command_timeout(self) -> None:
        assert c.DEFAULT_COMMAND_TIMEOUT >= c.MIN_COMMAND_TIMEOUT

    def test_idle_timeout(self) -> None:
        assert c.DEFAULT_IDLE_TIMEOUT_SECONDS >= c.MIN_IDLE_TIMEOUT_SECONDS

    def test_session_inactivity_timeout(self) -> None:
        assert c.DEFAULT_SESSION_INACTIVITY_TIMEOUT >= c.MIN_SESSION_INACTIVITY_TIMEOUT

    def test_tool_call_timeout(self) -> None:
        assert c.DEFAULT_TOOL_CALL_TIMEOUT >= c.MIN_TOOL_CALL_TIMEOUT

    def test_process_output_timeout(self) -> None:
        assert c.DEFAULT_PROCESS_OUTPUT_TIMEOUT >= c.MIN_PROCESS_OUTPUT_TIMEOUT

    def test_max_ping_failures(self) -> None:
        assert c.DEFAULT_MAX_PING_FAILURES >= c.MIN_MAX_PING_FAILURES

    def test_circuit_breaker_drain_timeout(self) -> None:
        assert c.DEFAULT_CIRCUIT_BREAKER_DRAIN_TIMEOUT >= c.MIN_CIRCUIT_BREAKER_DRAIN_TIMEOUT


class TestStateBranchConstants:
    """Verify git state branch constants."""

    def test_state_branch_name_is_string(self) -> None:
        assert isinstance(c.STATE_BRANCH_NAME, str)
        assert len(c.STATE_BRANCH_NAME) > 0

    def test_state_branch_name_value(self) -> None:
        assert c.STATE_BRANCH_NAME == "pokepoke-state"


class TestQualityScoringConstants:
    """Verify item quality scoring constants."""

    def test_needs_human_attention_defaults(self) -> None:
        assert c.DEFAULT_NEEDS_HUMAN_ATTENTION_FAILURES >= c.MIN_NEEDS_HUMAN_ATTENTION_FAILURES

    def test_min_needs_human_attention_positive(self) -> None:
        assert c.MIN_NEEDS_HUMAN_ATTENTION_FAILURES >= 1
