"""Shared fixtures for orchestration tests."""
from unittest.mock import patch, Mock
from contextlib import contextmanager

import pytest

from pokepoke.types import BeadsWorkItem, CopilotResult, GateAgentResult, WorkItemResult
from tests.fakes import FakeGitClient, FakeBeadsClient


@pytest.fixture(autouse=True)
def _mock_is_beads_item_closed():
    """Prevent bd subprocess calls from is_beads_item_closed in all orchestration tests.

    The function runs ``bd show <id> --json`` which hangs in CI/test
    environments where the beads daemon isn't running.
    """
    with patch(
        "pokepoke.beads.reconciliation.is_beads_item_closed",
        return_value=False,
    ):
        yield


# ---------------------------------------------------------------------------
# Mock Factories - Centralize patch targets
# ---------------------------------------------------------------------------


@contextmanager
def make_workflow_mocks(
    gate_success: bool = True,
    copilot_success: bool = True,
    has_parent: bool = False,
    merge_success: bool = True,
    close_success: bool = True,
):
    """Create standard mock stack for workflow tests.

    This replaces 14+ individual @patch decorators with a single context manager.
    When internal paths change, fix happens here instead of in 50+ tests.

    Args:
        gate_success: Whether gate agent should pass
        copilot_success: Whether copilot invocation succeeds
        has_parent: Whether item has a parent in hierarchy
        merge_success: Whether worktree merge succeeds
        close_success: Whether item close succeeds

    Yields:
        dict with all mocked objects
    """
    with (
        patch('pokepoke.orchestration.workflow.run_gate_agent') as mock_gate,
        patch('pokepoke.worktrees.worktree_finalization.close_parent_if_complete') as mock_close_parent,
        patch('pokepoke.worktrees.worktree_finalization.get_parent_id') as mock_get_parent,
        patch('pokepoke.worktrees.worktree_finalization.close_item') as mock_close,
        patch('subprocess.run') as mock_subprocess,
        patch('pokepoke.orchestration.workflow.cleanup_worktree') as mock_cleanup,
        patch('pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge') as mock_merge,
        patch('pokepoke.git.git_operations.has_uncommitted_changes') as mock_uncommitted,
        patch('os.chdir') as mock_chdir,
        patch('os.getcwd') as mock_getcwd,
        patch('pokepoke.orchestration.workflow.create_worktree') as mock_create_wt,
        patch('pokepoke.orchestration.workflow.assign_and_sync_item') as mock_assign,
        patch('pokepoke.orchestration.workflow.invoke_copilot') as mock_invoke,
        patch('builtins.input') as mock_input,
    ):
        # Configure defaults
        mock_input.return_value = 'y'
        mock_create_wt.return_value = '/tmp/worktree'
        mock_getcwd.return_value = '/original'
        mock_uncommitted.return_value = False
        mock_merge.return_value = (merge_success, merge_success)
        mock_close.return_value = close_success
        mock_assign.return_value = True

        # Smart parent ID lookup - returns parent for child, None for parent (no grandparent)
        def get_parent_side_effect(item_id: str) -> str | None:
            if has_parent and item_id.startswith("task-"):
                return "parent-1"
            return None
        mock_get_parent.side_effect = get_parent_side_effect

        mock_gate.return_value = GateAgentResult(
            success=gate_success,
            reason="Gate passed" if gate_success else "Gate failed"
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=copilot_success,
            output="Work completed" if copilot_success else "Failed",
            attempt_count=1
        )

        # Mock subprocess with smart command handling
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if 'rev-list' in cmd:
                return Mock(stdout="1\n", returncode=0)
            elif 'branch' in cmd and '--show-current' in cmd:
                return Mock(stdout="master\n", returncode=0)
            elif 'status' in cmd and '--porcelain' in cmd:
                return Mock(stdout="", returncode=0)
            elif cmd and cmd[0] == 'bd':
                if 'show' in cmd:
                    return Mock(stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]', returncode=0)
                elif 'sync' in cmd:
                    return Mock(stdout="", stderr="", returncode=0)
            elif 'checkout' in cmd or 'pull' in cmd or 'merge' in cmd or 'push' in cmd:
                return Mock(stdout="", returncode=0)
            return Mock(stdout="", returncode=0)

        mock_subprocess.side_effect = subprocess_side_effect

        yield {
            'gate': mock_gate,
            'close_parent': mock_close_parent,
            'get_parent': mock_get_parent,
            'close': mock_close,
            'subprocess': mock_subprocess,
            'cleanup': mock_cleanup,
            'merge': mock_merge,
            'uncommitted': mock_uncommitted,
            'chdir': mock_chdir,
            'getcwd': mock_getcwd,
            'create_wt': mock_create_wt,
            'assign': mock_assign,
            'invoke': mock_invoke,
            'input': mock_input,
        }


@contextmanager
def make_selection_mocks(selected_item: BeadsWorkItem | None = None):
    """Create mocks for work item selection tests.

    Args:
        selected_item: Item that hierarchical selection should return

    Yields:
        dict with selection mocks
    """
    with patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item') as mock_select:
        mock_select.return_value = selected_item
        yield {'select': mock_select}


# ---------------------------------------------------------------------------
# Test Data Builders - Create real objects instead of mocking
# ---------------------------------------------------------------------------


def make_work_item(
    item_id: str = "task-1",
    title: str = "Test Task",
    status: str = "open",
    priority: int = 1,
    issue_type: str = "task",
    assignee: str | None = None,
    **kwargs
) -> BeadsWorkItem:
    """Build a BeadsWorkItem with sensible defaults.

    This is better than mocking BeadsWorkItem because:
    1. It creates a real object with correct types
    2. It fails fast if BeadsWorkItem schema changes
    3. Tests are clearer about what data matters
    """
    # Handle 'id' keyword argument for convenience
    if 'id' in kwargs:
        item_id = kwargs.pop('id')

    return BeadsWorkItem(
        id=item_id,
        title=title,
        description=kwargs.pop('description', ''),
        status=status,
        priority=priority,
        issue_type=issue_type,
        assignee=assignee,
        **kwargs
    )


def make_copilot_result(
    work_item_id: str = "task-1",
    success: bool = True,
    output: str = "Work completed",
    attempt_count: int = 1,
    **kwargs
) -> CopilotResult:
    """Build a CopilotResult with sensible defaults."""
    return CopilotResult(
        work_item_id=work_item_id,
        success=success,
        output=output,
        attempt_count=attempt_count,
        **kwargs
    )


def make_gate_result(
    success: bool = True,
    reason: str | None = None,
    **kwargs
) -> GateAgentResult:
    """Build a GateAgentResult with sensible defaults."""
    return GateAgentResult(
        success=success,
        reason=reason or ("Gate passed" if success else "Gate failed"),
        **kwargs
    )


def make_work_item_result(
    success: bool = True,
    request_count: int = 1,
    cleanup_agent_runs: int = 0,
    gate_agent_runs: int = 1,
    **kwargs
) -> WorkItemResult:
    """Build a WorkItemResult with sensible defaults.

    Tests should focus on these outcome values rather than
    asserting which internal functions were called.
    """
    return WorkItemResult(
        success=success,
        request_count=request_count,
        cleanup_agent_runs=cleanup_agent_runs,
        gate_agent_runs=gate_agent_runs,
        **kwargs
    )


# ---------------------------------------------------------------------------
# Pytest Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_git() -> FakeGitClient:
    """Provide a FakeGitClient for tests.

    Prefer this over @patch('subprocess.run') for git operations.
    """
    return FakeGitClient()


@pytest.fixture
def fake_beads() -> FakeBeadsClient:
    """Provide a FakeBeadsClient for tests.

    Prefer this over @patch('pokepoke.beads.*') for beads operations.
    """
    return FakeBeadsClient()
