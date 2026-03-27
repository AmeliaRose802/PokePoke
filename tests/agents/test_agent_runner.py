"""Unit tests for agent_runner module.

This file is a stub that imports all test classes from split test modules.
Tests have been split by agent type for better organization:

- test_agent_runner_git.py: Git operations tests
- test_agent_runner_gates.py: Gate agent tests
- test_agent_runner_maintenance.py: Maintenance agent tests
- test_agent_runner_beads.py: Beads-only agent tests
- test_agent_runner_worktree.py: Worktree agent tests
- test_agent_runner_cleanup.py: Cleanup tests
- test_agent_runner_beta.py: Beta tester tests
- test_agent_runner_main_repo.py: Main repo agent tests
"""

# Import all test classes from split modules
from tests.agents.test_agent_runner_beads import (
    TestRunBeadsOnlyAgent,
)
from tests.agents.test_agent_runner_beta import (
    TestRunBetaTester,
)
from tests.agents.test_agent_runner_cleanup import (
    TestRunWorktreeCleanup,
    TestWorktreeCleanupPreCleanupRetry,
)
from tests.agents.test_agent_runner_gates import (
    TestGateAgentJsonDecodeError,
    TestGateAgentWithAgentId,
    TestRunGateAgent,
)
from tests.agents.test_agent_runner_git import (
    TestCommitAllChanges,
    TestHasUncommittedChanges,
)
from tests.agents.test_agent_runner_main_repo import (
    TestRunMainRepoAgent,
)
from tests.agents.test_agent_runner_maintenance import (
    TestMaintenanceAgentPromptMissing,
    TestRunMaintenanceAgent,
)
from tests.agents.test_agent_runner_worktree import (
    TestRunWorktreeAgent,
    TestWorktreeAgentCleanupFailureSetsResultFalse,
    TestWorktreeAgentFinallyCleanupException,
    TestWorktreeAgentMergeChangeFalse,
)

# Make test classes available for pytest discovery
__all__ = [
    # Git operations
    "TestHasUncommittedChanges",
    "TestCommitAllChanges",
    # Gate agent
    "TestRunGateAgent",
    "TestGateAgentJsonDecodeError",
    "TestGateAgentWithAgentId",
    # Maintenance agent
    "TestRunMaintenanceAgent",
    "TestMaintenanceAgentPromptMissing",
    # Beads-only agent
    "TestRunBeadsOnlyAgent",
    # Worktree agent
    "TestRunWorktreeAgent",
    "TestWorktreeAgentMergeChangeFalse",
    "TestWorktreeAgentFinallyCleanupException",
    "TestWorktreeAgentCleanupFailureSetsResultFalse",
    # Cleanup
    "TestRunWorktreeCleanup",
    "TestWorktreeCleanupPreCleanupRetry",
    # Beta tester
    "TestRunBetaTester",
    # Main repo agent
    "TestRunMainRepoAgent",
]
