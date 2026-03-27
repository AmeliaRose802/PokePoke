"""Unit tests for workflow module.

This file previously contained all workflow tests. Tests have been split into focused modules:

- test_workflow_selection.py: Work item selection (interactive, autonomous)
- test_workflow_worktree.py: Worktree lifecycle (setup, cleanup, locks)
- test_workflow_finalization.py: Work item finalization (merge, close)
- test_workflow_processing.py: Processing logic (Copilot invocation, retries, gate agent)
- test_workflow_errors.py: Error handling (failures, cleanup, exceptions)

This file is kept for any future tests that don't fit the above categories.
"""
