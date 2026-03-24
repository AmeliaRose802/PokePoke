"""Tests for RetryContext abstraction."""

import time

from pokepoke.orchestration.retry_context import NestedRetryContext, RetryContext


class TestRetryContext:
    """Test suite for RetryContext class."""

    def test_initialization_defaults(self):
        """Test RetryContext initializes with correct defaults."""
        ctx = RetryContext()
        assert ctx.max_retries is None
        assert ctx.timeout_seconds is None
        assert ctx.track_errors is False
        assert ctx.session_id is None
        assert ctx.retry_count == 0
        assert ctx.timeout_count == 0
        assert ctx.previous_errors == set()
        assert ctx.is_finished is False

    def test_initialization_with_params(self):
        """Test RetryContext initializes with provided parameters."""
        ctx = RetryContext(
            max_retries=3,
            timeout_seconds=60.0,
            track_errors=True,
            session_id="test-session"
        )
        assert ctx.max_retries == 3
        assert ctx.timeout_seconds == 60.0
        assert ctx.track_errors is True
        assert ctx.session_id == "test-session"

    def test_elapsed_time(self):
        """Test elapsed time tracking."""
        ctx = RetryContext()
        time.sleep(0.1)
        elapsed = ctx.elapsed()
        assert elapsed >= 0.1
        assert elapsed < 0.5  # Should be quick

    def test_is_timeout_exceeded_no_timeout(self):
        """Test timeout check when no timeout is set."""
        ctx = RetryContext()
        assert ctx.is_timeout_exceeded() is False

    def test_is_timeout_exceeded_not_exceeded(self):
        """Test timeout check when timeout is not exceeded."""
        ctx = RetryContext(timeout_seconds=10.0)
        assert ctx.is_timeout_exceeded() is False

    def test_is_timeout_exceeded_when_exceeded(self):
        """Test timeout check when timeout is exceeded."""
        ctx = RetryContext(timeout_seconds=0.1)
        time.sleep(0.15)
        assert ctx.is_timeout_exceeded() is True

    def test_is_retry_limit_exceeded_no_limit(self):
        """Test retry limit check when no limit is set."""
        ctx = RetryContext()
        ctx.retry_count = 100
        assert ctx.is_retry_limit_exceeded() is False

    def test_is_retry_limit_exceeded_not_exceeded(self):
        """Test retry limit check when limit is not exceeded."""
        ctx = RetryContext(max_retries=5)
        ctx.retry_count = 3
        assert ctx.is_retry_limit_exceeded() is False

    def test_is_retry_limit_exceeded_at_limit(self):
        """Test retry limit check when at the limit."""
        ctx = RetryContext(max_retries=3)
        ctx.retry_count = 3
        assert ctx.is_retry_limit_exceeded() is True

    def test_is_retry_limit_exceeded_over_limit(self):
        """Test retry limit check when over the limit."""
        ctx = RetryContext(max_retries=3)
        ctx.retry_count = 5
        assert ctx.is_retry_limit_exceeded() is True

    def test_can_retry_allowed(self):
        """Test can_retry when retries are allowed."""
        ctx = RetryContext(max_retries=3)
        ctx.retry_count = 2
        assert ctx.can_retry() is True

    def test_can_retry_at_limit(self):
        """Test can_retry when at retry limit."""
        ctx = RetryContext(max_retries=3)
        ctx.retry_count = 3
        assert ctx.can_retry() is False

    def test_can_retry_no_limit(self):
        """Test can_retry when no limit is set."""
        ctx = RetryContext()
        ctx.retry_count = 100
        assert ctx.can_retry() is True

    def test_should_continue_normal(self):
        """Test should_continue in normal execution."""
        ctx = RetryContext(max_retries=3, timeout_seconds=10.0)
        assert ctx.should_continue() is True

    def test_should_continue_when_finished(self):
        """Test should_continue when execution is finished."""
        ctx = RetryContext(max_retries=3, timeout_seconds=10.0)
        ctx.mark_finished()
        assert ctx.should_continue() is False

    def test_should_continue_when_timeout_exceeded(self):
        """Test should_continue when timeout is exceeded."""
        ctx = RetryContext(timeout_seconds=0.1)
        time.sleep(0.15)
        assert ctx.should_continue() is False

    def test_should_continue_when_retry_limit_exceeded(self):
        """Test should_continue when retry limit is exceeded."""
        ctx = RetryContext(max_retries=3)
        ctx.retry_count = 3
        assert ctx.should_continue() is False

    def test_record_retry(self):
        """Test retry counter increment."""
        ctx = RetryContext()
        assert ctx.retry_count == 0
        ctx.record_retry()
        assert ctx.retry_count == 1
        ctx.record_retry()
        assert ctx.retry_count == 2

    def test_record_timeout(self):
        """Test timeout counter increment."""
        ctx = RetryContext()
        assert ctx.timeout_count == 0
        ctx.record_timeout()
        assert ctx.timeout_count == 1
        ctx.record_timeout()
        assert ctx.timeout_count == 2

    def test_is_recurring_error_when_tracking_disabled(self):
        """Test recurring error detection when tracking is disabled."""
        ctx = RetryContext(track_errors=False)
        ctx.record_error("error1")
        assert ctx.is_recurring_error("error1") is False

    def test_is_recurring_error_when_not_seen(self):
        """Test recurring error detection for new error."""
        ctx = RetryContext(track_errors=True)
        assert ctx.is_recurring_error("new-error") is False

    def test_is_recurring_error_when_seen(self):
        """Test recurring error detection for previously seen error."""
        ctx = RetryContext(track_errors=True)
        ctx.record_error("error1")
        assert ctx.is_recurring_error("error1") is True

    def test_record_error_when_tracking_enabled(self):
        """Test error recording when tracking is enabled."""
        ctx = RetryContext(track_errors=True)
        ctx.record_error("error1")
        ctx.record_error("error2")
        assert "error1" in ctx.previous_errors
        assert "error2" in ctx.previous_errors
        assert len(ctx.previous_errors) == 2

    def test_record_error_when_tracking_disabled(self):
        """Test error recording when tracking is disabled."""
        ctx = RetryContext(track_errors=False)
        ctx.record_error("error1")
        assert len(ctx.previous_errors) == 0

    def test_mark_finished(self):
        """Test marking execution as finished."""
        ctx = RetryContext()
        assert ctx.is_finished is False
        ctx.mark_finished()
        assert ctx.is_finished is True

    def test_update_session_id(self):
        """Test session ID update."""
        ctx = RetryContext()
        assert ctx.session_id is None
        ctx.update_session_id("session-123")
        assert ctx.session_id == "session-123"
        ctx.update_session_id("session-456")
        assert ctx.session_id == "session-456"

    def test_reset_for_timeout_restart(self):
        """Test resetting context for timeout restart."""
        ctx = RetryContext(timeout_seconds=1.0, track_errors=True)
        ctx.update_session_id("session-123")
        ctx.record_error("error1")

        old_start_time = ctx.start_time
        time.sleep(0.05)

        ctx.reset_for_timeout_restart()

        # Timeout counter incremented
        assert ctx.timeout_count == 1

        # Start time reset
        assert ctx.start_time > old_start_time

        # Session ID and errors preserved
        assert ctx.session_id == "session-123"
        assert "error1" in ctx.previous_errors

    def test_multiple_timeout_restarts(self):
        """Test multiple timeout restarts."""
        ctx = RetryContext()
        ctx.reset_for_timeout_restart()
        ctx.reset_for_timeout_restart()
        ctx.reset_for_timeout_restart()
        assert ctx.timeout_count == 3


class TestNestedRetryContext:
    """Test suite for NestedRetryContext class."""

    def test_initialization(self):
        """Test NestedRetryContext initializes correctly."""
        outer = RetryContext(max_retries=3)
        inner = RetryContext(max_retries=5)
        nested = NestedRetryContext(outer=outer, inner=inner)

        assert nested.outer is outer
        assert nested.inner is inner

    def test_should_continue_both_allow(self):
        """Test should_continue when both contexts allow continuation."""
        outer = RetryContext(max_retries=3)
        inner = RetryContext(max_retries=5)
        nested = NestedRetryContext(outer=outer, inner=inner)

        assert nested.should_continue() is True

    def test_should_continue_outer_blocks(self):
        """Test should_continue when outer context blocks."""
        outer = RetryContext(max_retries=3)
        outer.retry_count = 3
        inner = RetryContext(max_retries=5)
        nested = NestedRetryContext(outer=outer, inner=inner)

        assert nested.should_continue() is False

    def test_should_continue_inner_blocks(self):
        """Test should_continue when inner context blocks."""
        outer = RetryContext(max_retries=3)
        inner = RetryContext(max_retries=5)
        inner.retry_count = 5
        nested = NestedRetryContext(outer=outer, inner=inner)

        assert nested.should_continue() is False

    def test_should_continue_both_block(self):
        """Test should_continue when both contexts block."""
        outer = RetryContext(max_retries=3)
        outer.retry_count = 3
        inner = RetryContext(max_retries=5)
        inner.retry_count = 5
        nested = NestedRetryContext(outer=outer, inner=inner)

        assert nested.should_continue() is False

    def test_record_outer_retry(self):
        """Test recording outer retry."""
        outer = RetryContext(max_retries=3)
        inner = RetryContext(max_retries=5)
        nested = NestedRetryContext(outer=outer, inner=inner)

        assert outer.retry_count == 0
        nested.record_outer_retry()
        assert outer.retry_count == 1
        assert inner.retry_count == 0

    def test_record_inner_retry(self):
        """Test recording inner retry."""
        outer = RetryContext(max_retries=3)
        inner = RetryContext(max_retries=5)
        nested = NestedRetryContext(outer=outer, inner=inner)

        assert inner.retry_count == 0
        nested.record_inner_retry()
        assert inner.retry_count == 1
        assert outer.retry_count == 0

    def test_reset_inner(self):
        """Test resetting inner context."""
        outer = RetryContext(max_retries=3)
        inner = RetryContext(max_retries=5)
        inner.retry_count = 3
        inner.timeout_count = 2
        nested = NestedRetryContext(outer=outer, inner=inner)

        old_start_time = inner.start_time
        time.sleep(0.05)

        nested.reset_inner()

        assert inner.retry_count == 0
        assert inner.timeout_count == 0
        assert inner.start_time > old_start_time
        assert outer.retry_count == 0  # Outer unchanged

    def test_nested_retry_workflow(self):
        """Test realistic nested retry workflow."""
        # Simulate gate agent: 3 crash retries, 3 timeout retries each
        outer = RetryContext(max_retries=3)
        inner = RetryContext(max_retries=3)
        nested = NestedRetryContext(outer=outer, inner=inner)

        # First outer attempt
        assert nested.should_continue() is True

        # Inner retry 1
        nested.record_inner_retry()
        assert nested.should_continue() is True
        assert inner.retry_count == 1

        # Inner retry 2
        nested.record_inner_retry()
        assert nested.should_continue() is True
        assert inner.retry_count == 2

        # Inner retry 3 - limit reached
        nested.record_inner_retry()
        assert nested.should_continue() is False
        assert inner.retry_count == 3

        # Outer retry - reset inner
        nested.record_outer_retry()
        nested.reset_inner()
        assert nested.should_continue() is True
        assert outer.retry_count == 1
        assert inner.retry_count == 0

        # Continue with reset inner context
        nested.record_inner_retry()
        assert nested.should_continue() is True
