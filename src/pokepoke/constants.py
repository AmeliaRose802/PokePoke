"""Named constants for timeouts, thresholds, and operational limits.

Centralises magic numbers so that every module references a single source of
truth.  Each constant is documented with its unit and purpose.
"""

# ---------------------------------------------------------------------------
# Preflight health-check constants
# ---------------------------------------------------------------------------

# Default values used when no override is specified in config file.
DEFAULT_MIN_DISK_SPACE_GB = 1.0  # Default disk space requirement (GB)
DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0  # Default lock acquisition timeout (seconds)
DEFAULT_WORKTREE_TEST_TIMEOUT = 60.0  # Default worktree operation test timeout (seconds)
DEFAULT_MAX_ORPHAN_WORKTREES = 50  # Default max orphan worktrees before cleanup
DEFAULT_GIT_OPERATION_TIMEOUT = 30.0  # Default git operation timeout (seconds)
DEFAULT_MAX_REPAIR_ATTEMPTS = 3  # Default repair attempts before giving up

# Minimum floor values — configured values are clamped to at least these.
MIN_DISK_SPACE_GB = 0.1  # Minimum disk space requirement (GB)
MIN_LOCK_TIMEOUT_SECONDS = 5.0  # Minimum lock acquisition timeout (seconds)
MIN_WORKTREE_TEST_TIMEOUT = 10.0  # Minimum worktree operation timeout (seconds)
MIN_ORPHAN_WORKTREES = 0  # Minimum allowed orphan worktrees (0 = unlimited)
MIN_GIT_OPERATION_TIMEOUT = 5.0  # Minimum git operation timeout (seconds)
MIN_REPAIR_ATTEMPTS = 1  # Minimum repair attempts before giving up

# ---------------------------------------------------------------------------
# Performance threshold constants
# ---------------------------------------------------------------------------

# Default values for performance monitoring thresholds.
DEFAULT_MAX_MERGE_QUEUE_DEPTH = 5  # Merge queue depth alert threshold
DEFAULT_MAX_LOCK_WAIT_SECONDS = 30.0  # Max acceptable lock wait time (seconds)
DEFAULT_MAX_ITERATION_SECONDS = 30.0  # Max acceptable iteration duration (seconds)
DEFAULT_MIN_MEMORY_MB = 256.0  # Minimum free memory to continue (MB)
DEFAULT_MIN_SUCCESS_RATE = 0.5  # Minimum acceptable success rate (0.0–1.0)

# Minimum floor values for performance thresholds.
MIN_MERGE_QUEUE_DEPTH = 1  # Must allow at least one item in queue
MIN_LOCK_WAIT_SECONDS = 1.0  # Minimum lock wait threshold (seconds)
MIN_ITERATION_SECONDS = 1.0  # Minimum iteration time threshold (seconds)
MIN_MEMORY_MB = 32.0  # Absolute minimum memory floor (MB)

# ---------------------------------------------------------------------------
# Project / orchestration session constants
# ---------------------------------------------------------------------------

# Default values for project-level orchestration settings.
DEFAULT_MAX_PARALLEL_AGENTS = 1  # Default number of concurrent agents
DEFAULT_COMMAND_TIMEOUT = 600  # Default timeout for long-running commands (seconds)
DEFAULT_MAX_COPILOT_FAILURE_RETRIES = 2  # Default retries when Copilot session fails
DEFAULT_IDLE_TIMEOUT_SECONDS = 90  # Default seconds before confirming session idle
DEFAULT_SESSION_INACTIVITY_TIMEOUT = 900  # Default no-SDK-event timeout (seconds)
DEFAULT_TOOL_CALL_TIMEOUT = 1800  # Default max single tool invocation (seconds)
DEFAULT_PROCESS_OUTPUT_TIMEOUT = 600  # Default no-output timeout (seconds)
DEFAULT_MAX_PING_FAILURES = 3  # Default consecutive ping failures before dead
DEFAULT_CIRCUIT_BREAKER_DRAIN_TIMEOUT = 1800  # Default max wait for agents after circuit breaker trips (seconds, 0 = wait forever)

# Minimum floor values for orchestration settings.
MIN_MAX_PARALLEL_AGENTS = 1  # Must have at least one agent
MIN_COMMAND_TIMEOUT = 30  # Minimum command timeout (seconds)
MIN_IDLE_TIMEOUT_SECONDS = 10  # Minimum idle timeout (seconds)
MIN_SESSION_INACTIVITY_TIMEOUT = 60  # Minimum inactivity timeout (seconds)
MIN_TOOL_CALL_TIMEOUT = 60  # Minimum tool call timeout (seconds)
MIN_PROCESS_OUTPUT_TIMEOUT = 30  # Minimum process output timeout (seconds)
MIN_MAX_PING_FAILURES = 1  # Must allow at least one ping failure
MIN_CIRCUIT_BREAKER_DRAIN_TIMEOUT = 0  # Minimum drain timeout (0 = wait forever)

# ---------------------------------------------------------------------------
# Item quality scoring constants
# ---------------------------------------------------------------------------

# Consecutive failures before an item is flagged as needing human attention.
DEFAULT_NEEDS_HUMAN_ATTENTION_FAILURES = 3
MIN_NEEDS_HUMAN_ATTENTION_FAILURES = 1  # Must allow at least one failure
