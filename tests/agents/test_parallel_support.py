"""Tests for parallel_support helper functions.

This is the main test file for parallel_support module. Most tests have been
split into focused modules:
- test_parallel_support_preflight.py: Preflight health checks and error handling
- test_parallel_support_workers.py: Worker finalization and cleanup
- test_parallel_support_circuit_breaker.py: Circuit breaker functionality
- test_parallel_support_dispatch.py: Item dispatching and scheduling
- test_parallel_support_orchestration.py: Orchestration helper functions

This file is maintained for backward compatibility and may contain integration
tests or tests that don't fit neatly into the focused modules.
"""

# All tests have been extracted to focused modules.
# This file is kept for backward compatibility.
# Import the test classes from the focused modules if needed:
#
# from test_parallel_support_preflight import (
#     TestHandlePreflightChecks,
#     TestFormatPreflightErrors,
#     TestPreflightRateLimiting,
# )
# from test_parallel_support_workers import (
#     TestFinalizeWorkers,
#     TestDrainOrphanedFutures,
# )
# from test_parallel_support_circuit_breaker import (
#     TestDrainCircuitBreaker,
#     TestUpdateCircuitBreaker,
# )
# from test_parallel_support_dispatch import (
#     TestDispatchItems,
#     TestDispatchHighConflictItems,
# )
# from test_parallel_support_orchestration import (
#     TestRunPreflightAndRepoChecks,
#     TestCheckLoopExit,
#     TestComputeSlots,
# )
