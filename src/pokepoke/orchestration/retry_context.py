"""Unified retry/timeout context for agent orchestration.

This module provides a reusable RetryContext abstraction that deduplicates
retry and timeout patterns across work, gate, and cleanup agents.
"""

import time
from dataclasses import dataclass, field


@dataclass
class RetryContext:
    """Context for managing retries and timeouts in agent execution.

    This class encapsulates common retry/timeout logic used across agents:
    - Timeout tracking with elapsed time checks
    - Retry attempt counting with configurable limits
    - Session resumption support
    - Error tracking for recurring error detection

    Attributes:
        max_retries: Maximum number of retry attempts (None = unlimited)
        timeout_seconds: Maximum execution time in seconds (None = no timeout)
        track_errors: Whether to track errors for recurring error detection
        session_id: Optional session identifier for resumption
        start_time: Timestamp when context was created
        retry_count: Current number of retry attempts
        timeout_count: Number of timeout events
        previous_errors: Set of previously seen error messages (if track_errors=True)
        is_finished: Whether execution is complete
    """

    max_retries: int | None = None
    timeout_seconds: float | None = None
    track_errors: bool = False
    session_id: str | None = None

    start_time: float = field(default_factory=time.time, init=False)
    retry_count: int = field(default=0, init=False)
    timeout_count: int = field(default=0, init=False)
    previous_errors: set[str] = field(default_factory=set, init=False)
    is_finished: bool = field(default=False, init=False)

    def elapsed(self) -> float:
        """Get elapsed time since context creation."""
        return time.time() - self.start_time

    def is_timeout_exceeded(self) -> bool:
        """Check if timeout has been exceeded.

        Returns:
            True if timeout_seconds is set and elapsed time exceeds it
        """
        if self.timeout_seconds is None:
            return False
        return self.elapsed() >= self.timeout_seconds

    def is_retry_limit_exceeded(self) -> bool:
        """Check if retry limit has been exceeded.

        Returns:
            True if max_retries is set and retry_count exceeds it
        """
        if self.max_retries is None:
            return False
        return self.retry_count >= self.max_retries

    def can_retry(self) -> bool:
        """Check if another retry attempt is allowed.

        Returns:
            True if retry limit has not been exceeded
        """
        return not self.is_retry_limit_exceeded()

    def should_continue(self) -> bool:
        """Check if execution should continue.

        Returns:
            True if not finished, timeout not exceeded, and retries allowed
        """
        if self.is_finished:
            return False
        if self.is_timeout_exceeded():
            return False
        if self.is_retry_limit_exceeded():
            return False
        return True

    def record_retry(self) -> None:
        """Increment retry counter."""
        self.retry_count += 1

    def record_timeout(self) -> None:
        """Increment timeout counter."""
        self.timeout_count += 1

    def is_recurring_error(self, error_message: str) -> bool:
        """Check if error has been seen before.

        Args:
            error_message: Error message to check

        Returns:
            True if error_message was previously recorded
        """
        if not self.track_errors:
            return False
        return error_message in self.previous_errors

    def record_error(self, error_message: str) -> None:
        """Record an error for recurring error detection.

        Args:
            error_message: Error message to track
        """
        if self.track_errors:
            self.previous_errors.add(error_message)

    def mark_finished(self) -> None:
        """Mark execution as complete."""
        self.is_finished = True

    def update_session_id(self, session_id: str) -> None:
        """Update session ID for resumption.

        Args:
            session_id: New session identifier
        """
        self.session_id = session_id

    def reset_for_timeout_restart(self) -> None:
        """Reset context for a timeout restart.

        Increments timeout counter and resets start time while preserving
        session_id and error tracking.
        """
        self.record_timeout()
        self.start_time = time.time()


@dataclass
class NestedRetryContext:
    """Context for managing nested retry loops (e.g., crash + timeout retries).

    Some agents need multiple retry dimensions (e.g., gate agent with both
    crash retries and timeout retries). This class manages nested retry contexts.

    Attributes:
        outer: Outer retry context (e.g., crash retries)
        inner: Inner retry context (e.g., timeout retries)
    """

    outer: RetryContext
    inner: RetryContext

    def should_continue(self) -> bool:
        """Check if execution should continue.

        Returns:
            True if both outer and inner contexts allow continuation
        """
        return self.outer.should_continue() and self.inner.should_continue()

    def record_outer_retry(self) -> None:
        """Record outer retry attempt."""
        self.outer.record_retry()

    def record_inner_retry(self) -> None:
        """Record inner retry attempt."""
        self.inner.record_retry()

    def reset_inner(self) -> None:
        """Reset inner retry context."""
        self.inner.retry_count = 0
        self.inner.timeout_count = 0
        self.inner.start_time = time.time()
