"""Shared fixtures for orchestration tests."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    CopilotResult,
    GateAgentResult,
    WorkItemResult,
)
from tests.fakes import FakeBeadsClient, FakeGitClient


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


@pytest.fixture(autouse=True)
def _mock_gate_rejection_count():
    """Prevent bd subprocess calls from get_gate_rejection_count in all orchestration tests."""
    with patch(
        "pokepoke.beads.beads_management.get_gate_rejection_count",
        return_value=0,
    ):
        yield


# ---------------------------------------------------------------------------
# Patch target constants – single source of truth for module paths.
# When a function is moved/renamed, update ONE line here.
# ---------------------------------------------------------------------------

# -- orchestrator module targets --
_ORCH = "pokepoke.orchestration.orchestrator"
PATCH_GET_READY_ITEMS = f"{_ORCH}.get_ready_work_items"
PATCH_SELECT_WORK_ITEM = f"{_ORCH}.select_work_item"
PATCH_PROCESS_WORK_ITEM = f"{_ORCH}.process_work_item"
PATCH_RUN_BETA_TESTER_ORCH = f"{_ORCH}.run_beta_tester"
PATCH_RUN_PERIODIC_MAINTENANCE = f"{_ORCH}.run_periodic_maintenance"
PATCH_CHECK_AND_COMMIT = f"{_ORCH}.check_and_commit_main_repo"
PATCH_GET_BEADS_STATS = f"{_ORCH}.get_beads_stats"
PATCH_RECORD_COMPLETION = f"{_ORCH}.record_completion"
PATCH_CLEAR_BANNER = f"{_ORCH}.clear_terminal_banner"
PATCH_PRINT_STATS = f"{_ORCH}.print_stats"
PATCH_INIT_AGENT_NAME = f"{_ORCH}.initialize_agent_name"
PATCH_RUN_WORKTREE_CLEANUP = "pokepoke.agents.agent_runner.run_worktree_cleanup"
PATCH_ORCH_IS_SHUTTING_DOWN = f"{_ORCH}.is_shutting_down"

# -- workflow / process_work_item targets --
_WF = "pokepoke.orchestration.workflow"
_WFH = "pokepoke.orchestration.workflow_helpers"
PATCH_WF_INVOKE_COPILOT = f"{_WF}.invoke_copilot"
PATCH_WF_RUN_GATE_AGENT = f"{_WF}.run_gate_agent"
PATCH_WF_ASSIGN = f"{_WF}.assign_and_sync_item"
PATCH_WF_SETUP_WORKTREE = f"{_WF}.setup_worktree"
PATCH_WF_CLEANUP_WORKTREE = f"{_WF}.cleanup_worktree"
PATCH_WF_CLEANUP_TIMEOUT = f"{_WF}.run_cleanup_with_timeout"
PATCH_WF_GET_CONFIG = f"{_WF}.get_config"
PATCH_WF_IS_SHUTTING_DOWN = f"{_WF}.is_shutting_down"
PATCH_WF_SELECT_MODEL = f"{_WF}.select_model_for_item"
PATCH_WF_ADD_COMMENT = f"{_WF}.add_comment"
PATCH_WFH_UNCOMMITTED = f"{_WFH}.has_uncommitted_changes"
PATCH_WFH_FINALIZE = f"{_WFH}.finalize_work_item"
PATCH_WFH_BETA_TESTER = f"{_WFH}.run_beta_tester"
PATCH_WFH_CREATE_WORKTREE = f"{_WFH}.create_worktree"
PATCH_WFH_CLEANUP_LOOP = f"{_WFH}.run_cleanup_loop"
PATCH_GIT_HANDOFF = "pokepoke.git.git_operations.build_handoff_context"
PATCH_GIT_COMMITS_AHEAD = "pokepoke.git.git_operations.has_commits_ahead"
PATCH_GIT_UNCOMMITTED = "pokepoke.git.git_operations.has_uncommitted_changes"
PATCH_MODEL_CONFIG = "pokepoke.models.model_selection.get_config"

# -- worktree finalization targets --
_FIN = "pokepoke.worktrees.worktree_finalization"
PATCH_FIN_CLOSE_ITEM = f"{_FIN}.close_item"
PATCH_FIN_CLOSE_PARENT = f"{_FIN}.close_parent_if_complete"
PATCH_FIN_GET_PARENT = f"{_FIN}.get_parent_id"
PATCH_FIN_MERGE_WT = f"{_FIN}.merge_worktree_to_dev"
PATCH_FIN_CHECK_MERGE = f"{_FIN}.check_and_merge_worktree"
PATCH_FIN_CLOSE_PARENTS = f"{_FIN}.close_work_item_and_parents"
PATCH_FIN_CHECK_HIERARCHY = f"{_FIN}.check_parent_hierarchy"
PATCH_FIN_MERGE_LOCK = f"{_FIN}.merge_lock"
PATCH_FIN_RUN_BD = f"{_FIN}._run_bd_with_retry"
PATCH_PERFORM_MERGE = "pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge"

# -- selection targets --
PATCH_SELECT_HIERARCHICAL = "pokepoke.orchestration.work_item_selection.select_next_hierarchical_item"

# -- __main__ targets --
PATCH_MAIN_RUN_ORCH = "pokepoke.__main__.run_orchestrator"
PATCH_ENSURE_READY = "pokepoke.utils.project_utils.ensure_project_ready"
PATCH_INIT_PROJECT = "pokepoke.init.init_project"
PATCH_UI = "pokepoke.desktop.terminal_ui.ui"


# ---------------------------------------------------------------------------
# Mock Factories - Centralize patch targets
# ---------------------------------------------------------------------------


_sentinel = object()


@contextmanager
def make_orchestrator_mocks(
    *,
    items: list[BeadsWorkItem] | None = None,
    selected: BeadsWorkItem | None = _sentinel,
    process_result: WorkItemResult | None = None,
    include_maintenance: bool = False,
    include_check_repo: bool = False,
    include_stats: bool = False,
    include_sleep: bool = False,
    include_input: bool = False,
    include_agent_name: bool = False,
    include_record: bool = False,
):
    """Create standard mock stack for ``run_orchestrator`` tests.

    Centralizes the 6-10 most common patch targets.  When internal
    module paths change, update the ``PATCH_*`` constants above.

    Yields:
        dict with keyed mocks (e.g. ``mocks['get_items']``)
    """
    stack = ExitStack()
    mocks: dict[str, Mock] = {}

    with stack:
        # -- always-present patches (the core 6) --
        mocks['subprocess'] = stack.enter_context(patch('subprocess.run'))
        mocks['worktree_cleanup'] = stack.enter_context(patch(PATCH_RUN_WORKTREE_CLEANUP))
        mocks['beta'] = stack.enter_context(patch(PATCH_RUN_BETA_TESTER_ORCH))
        mocks['process'] = stack.enter_context(patch(PATCH_PROCESS_WORK_ITEM))
        mocks['select'] = stack.enter_context(patch(PATCH_SELECT_WORK_ITEM))
        mocks['get_items'] = stack.enter_context(patch(PATCH_GET_READY_ITEMS))

        # -- optional patches (added via flags) --
        if include_maintenance:
            mocks['maintenance'] = stack.enter_context(patch(PATCH_RUN_PERIODIC_MAINTENANCE))
            mocks['maintenance'].return_value = None
        if include_check_repo:
            mocks['check_repo'] = stack.enter_context(patch(PATCH_CHECK_AND_COMMIT))
            mocks['check_repo'].return_value = True
        if include_stats:
            mocks['beads_stats'] = stack.enter_context(patch(PATCH_GET_BEADS_STATS))
            mocks['beads_stats'].return_value = {}
        if include_sleep:
            mocks['sleep'] = stack.enter_context(patch('time.sleep'))
        if include_input:
            mocks['input'] = stack.enter_context(patch('builtins.input'))
        if include_agent_name:
            mocks['init_agent_name'] = stack.enter_context(patch(PATCH_INIT_AGENT_NAME))
            mocks['init_agent_name'].return_value = "pokepoke_test_agent"
        if include_record:
            mocks['record'] = stack.enter_context(patch(PATCH_RECORD_COMPLETION))

        # -- configure defaults --
        mocks['subprocess'].return_value = Mock(stdout="", returncode=0)
        mocks['beta'].return_value = None

        if items is not None:
            mocks['get_items'].return_value = items
        else:
            mocks['get_items'].return_value = []

        if selected is not _sentinel:
            mocks['select'].return_value = selected
        else:
            mocks['select'].return_value = None

        if process_result is not None:
            mocks['process'].return_value = process_result
        else:
            mocks['process'].return_value = WorkItemResult(
                success=True, request_count=1, stats=AgentStats()
            )

        yield mocks


@contextmanager
def make_process_item_mocks(
    *,
    copilot_success: bool = True,
    gate_success: bool = True,
    gate_result: GateAgentResult | None = None,
    assign_ok: bool = True,
    worktree_path: str | Path = "/fake/worktree",
    uncommitted: bool = False,
    commits_ahead: int = 1,
    finalize_ok: bool = True,
    include_config: bool = False,
    include_handoff: bool = False,
    include_session_cleanup: bool = False,
    include_cleanup_worktree: bool = False,
    max_copilot_failure_retries: int = 0,
):
    """Create standard mock stack for ``process_work_item`` tests.

    Centralizes the 12-15 most common patch targets used when testing
    the inner workflow loop.  When internal paths change, update the
    ``PATCH_*`` constants at the top of this module.

    Yields:
        dict with keyed mocks.
    """
    stack = ExitStack()
    mocks: dict[str, Mock] = {}

    with stack:
        # -- always-present patches (the core set) --
        mocks['time'] = stack.enter_context(patch('time.time'))
        mocks['input'] = stack.enter_context(patch('builtins.input'))
        mocks['assign'] = stack.enter_context(patch(PATCH_WF_ASSIGN))
        mocks['setup'] = stack.enter_context(patch(PATCH_WF_SETUP_WORKTREE))
        mocks['uncommitted'] = stack.enter_context(patch(PATCH_WFH_UNCOMMITTED))
        mocks['invoke'] = stack.enter_context(patch(PATCH_WF_INVOKE_COPILOT))
        mocks['cleanup_timeout'] = stack.enter_context(patch(PATCH_WF_CLEANUP_TIMEOUT))
        mocks['getcwd'] = stack.enter_context(patch('os.getcwd'))
        mocks['chdir'] = stack.enter_context(patch('os.chdir'))
        mocks['finalize'] = stack.enter_context(patch(PATCH_WFH_FINALIZE))
        mocks['beta'] = stack.enter_context(patch(PATCH_WFH_BETA_TESTER))
        mocks['gate'] = stack.enter_context(patch(PATCH_WF_RUN_GATE_AGENT))
        mocks['commits_ahead'] = stack.enter_context(patch(PATCH_GIT_COMMITS_AHEAD))

        # -- optional patches --
        if include_handoff:
            mocks['handoff'] = stack.enter_context(
                patch(PATCH_GIT_HANDOFF, return_value='')
            )
        if include_config:
            mocks['config'] = stack.enter_context(patch(PATCH_WF_GET_CONFIG))
            cfg = mocks['config'].return_value
            cfg.max_copilot_failure_retries = max_copilot_failure_retries
            cfg.gate_agent_enabled = True
            cfg.ai_backend.provider = "copilot"
            cfg.command_timeout = 300
            cfg.max_parallel_agents = 1
            cfg.max_gate_rejections_per_item = 3
        if include_session_cleanup:
            from pokepoke.orchestration.work_item_session import WorkItemSession
            mocks['session_cleanup'] = stack.enter_context(
                patch.object(WorkItemSession, 'cleanup_on_failure')
            )
        if include_cleanup_worktree:
            mocks['cleanup_wt'] = stack.enter_context(
                patch(PATCH_WF_CLEANUP_WORKTREE)
            )

        # -- configure defaults --
        mocks['time'].return_value = 0.0
        mocks['input'].return_value = 'y'
        mocks['assign'].return_value = assign_ok
        mocks['setup'].return_value = Path(str(worktree_path)) if worktree_path else None
        mocks['getcwd'].return_value = "/original"
        mocks['uncommitted'].return_value = uncommitted
        mocks['commits_ahead'].return_value = commits_ahead
        mocks['cleanup_timeout'].return_value = (True, 0)
        mocks['finalize'].return_value = finalize_ok
        mocks['beta'].return_value = None

        if gate_result is not None:
            mocks['gate'].return_value = gate_result
        else:
            mocks['gate'].return_value = GateAgentResult(
                success=gate_success,
                reason="Gate passed" if gate_success else "Gate failed",
            )
        mocks['invoke'].return_value = CopilotResult(
            work_item_id="task-1",
            success=copilot_success,
            output="Work completed" if copilot_success else "",
            error="" if copilot_success else "Failed",
            attempt_count=1,
        )

        yield mocks


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
        patch(PATCH_WF_RUN_GATE_AGENT) as mock_gate,
        patch(PATCH_FIN_CLOSE_PARENT) as mock_close_parent,
        patch(PATCH_FIN_GET_PARENT) as mock_get_parent,
        patch(PATCH_FIN_CLOSE_ITEM) as mock_close,
        patch(PATCH_FIN_RUN_BD) as mock_run_bd,
        patch('subprocess.run') as mock_subprocess,
        patch(PATCH_WF_CLEANUP_WORKTREE) as mock_cleanup,
        patch(PATCH_PERFORM_MERGE) as mock_merge,
        patch(PATCH_GIT_UNCOMMITTED) as mock_uncommitted,
        patch('os.chdir') as mock_chdir,
        patch('os.getcwd') as mock_getcwd,
        patch('pokepoke.orchestration.workflow.setup_worktree') as mock_create_wt,
        patch(PATCH_WF_ASSIGN) as mock_assign,
        patch(PATCH_WF_INVOKE_COPILOT) as mock_invoke,
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

        # Mock _run_bd_with_retry for worktree_finalization's item status check
        # Returns an item with status "open" so the "agent did not close" path is taken
        mock_run_bd.return_value = Mock(
            stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]',
            returncode=0
        )

        yield {
            'gate': mock_gate,
            'close_parent': mock_close_parent,
            'get_parent': mock_get_parent,
            'close': mock_close,
            'run_bd': mock_run_bd,
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
    with patch(PATCH_SELECT_HIERARCHICAL) as mock_select:
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
