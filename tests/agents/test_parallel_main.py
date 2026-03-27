"""Tests for the parallel orchestrator loop module.

This module now serves as the main entry point for parallel orchestration tests.
Individual test groups have been split into focused modules:

- test_parallel_basics.py: Core functions (_parallel_process_item, _collect_done_futures)
- test_parallel_loop.py: Main loop behavior, continuous mode, shutdown handling
- test_parallel_scaling.py: Resource management, dynamic scaling, stats updates
- test_parallel_replenishment.py: Batch replenishment, circuit breaker, crash handling

For legacy compatibility, some tests may remain in this file that don't fit the
categories above, or tests that require the full integration context.
"""

# This file intentionally kept minimal after splitting tests into focused modules.
# If you're looking for specific parallel tests, check the module docstrings above.
