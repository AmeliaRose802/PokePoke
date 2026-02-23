"""Integration tests for worktree merge handler module.

Tests for perform_worktree_merge and handle_worktree_merge to improve coverage
of critical merge sequence logic.
"""

from pathlib import Path
from unittest.mock import patch, Mock, MagicMock
import pytest

from pokepoke.types import BeadsWorkItem
from pokepoke.worktree_merge_handler import (
    handle_worktree_merge,
    perform_worktree_merge,
)


def _make_test_item(item_id: str = "test-item") -> BeadsWorkItem:
    """Create a test BeadsWorkItem."""
    return BeadsWorkItem(
        id=item_id,
        title="Test Item",
        status="ready",
        priority=1,
        issue_type="task",
    )


class TestPerformWorktreeMergeIntegration:
    """Integration tests for perform_worktree_merge."""

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.merge_worktree')
    @patch('pokepoke.worktree_cleanup.remove_from_manifest')
    def test_perform_merge_success_path(
        self,
        mock_remove_manifest,
        mock_merge,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test successful merge path without cleanup agent."""
        mock_check_ready.return_value = (True, '')
        mock_merge.return_value = (True, [])
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-123')
        worktree_path = Path('C:/repos/worktrees/task-test-123')

        success, cleaned = perform_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is True
        assert cleaned is True
        mock_check_ready.assert_called_once()
        mock_merge.assert_called_once_with(agent_item.id)

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.invoke_cleanup_agent')
    def test_perform_merge_invokes_cleanup_agent_when_repo_not_ready(
        self,
        mock_invoke_cleanup,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that cleanup agent is invoked when main repo is not ready."""
        # First check fails, second succeeds after cleanup
        mock_check_ready.side_effect = [
            (False, 'Repo has uncommitted changes'),
            (True, '')
        ]
        mock_invoke_cleanup.return_value = (True, None)
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-456')
        worktree_path = Path('C:/repos/worktrees/task-test-456')

        with patch('pokepoke.worktree_merge_handler.merge_worktree', return_value=(True, [])):
            success, cleaned = perform_worktree_merge(
                item_id=agent_item.id,
                item=agent_item,
                worktree_path=worktree_path,
                repo_root=Path('C:/repos'),
                parent_agent_id='parent-123'
            )

        assert success is True
        mock_invoke_cleanup.assert_called_once()
        # Should pass parent_agent_id for nesting
        call_args = mock_invoke_cleanup.call_args
        assert call_args[1]['parent_agent_id'] == 'parent-123'

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.invoke_cleanup_agent')
    def test_perform_merge_fails_when_cleanup_agent_fails(
        self,
        mock_invoke_cleanup,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that merge fails if cleanup agent cannot fix the repo state."""
        mock_check_ready.side_effect = [
            (False, 'Repo has uncommitted changes'),
            (False, 'Repo still dirty after cleanup')
        ]
        mock_invoke_cleanup.return_value = (False, None)
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-789')
        worktree_path = Path('C:/repos/worktrees/task-test-789')

        success, cleaned = perform_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is False
        assert cleaned is False

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.merge_worktree')
    @patch('pokepoke.worktree_merge_handler.invoke_merge_conflict_cleanup_agent')
    def test_perform_merge_handles_merge_conflicts(
        self,
        mock_conflict_agent,
        mock_merge,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test handling of merge conflicts."""
        mock_check_ready.return_value = (True, '')
        mock_merge.return_value = (False, ['file1.py', 'file2.py'])
        mock_conflict_agent.return_value = (True, None)
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-conflicts')
        worktree_path = Path('C:/repos/worktrees/task-test-conflicts')

        success, cleaned = perform_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is False
        mock_conflict_agent.assert_called_once()
        # Verify conflict files were passed to agent
        call_args = mock_conflict_agent.call_args
        assert 'file1.py' in str(call_args)

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.merge_worktree')
    @patch('pokepoke.worktree_cleanup.add_uncleaned_worktree')
    def test_perform_merge_tracks_uncleaned_worktree_on_failure(
        self,
        mock_add_uncleaned,
        mock_merge,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that failed merges track uncleaned worktrees."""
        mock_check_ready.return_value = (True, '')
        mock_merge.return_value = (False, [])  # Failed, no conflicts
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-failed')
        worktree_path = Path('C:/repos/worktrees/task-test-failed')

        success, cleaned = perform_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is False
        assert cleaned is False
        mock_add_uncleaned.assert_called_once()

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.merge_worktree')
    @patch('pokepoke.worktree_cleanup.remove_from_manifest')
    def test_perform_merge_removes_from_manifest_on_success(
        self,
        mock_remove_manifest,
        mock_merge,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that successful merge removes worktree from manifest."""
        mock_check_ready.return_value = (True, '')
        mock_merge.return_value = (True, [])
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-manifest')
        worktree_path = Path('C:/repos/worktrees/task-test-manifest')

        success, cleaned = perform_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is True
        mock_remove_manifest.assert_called_once_with(agent_item.id)


class TestHandleWorktreeMergeIntegration:
    """Integration tests for handle_worktree_merge with merge lock."""

    @patch('pokepoke.worktree_merge_handler.merge_lock')
    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_handle_merge_acquires_lock(
        self,
        mock_perform,
        mock_merge_lock
    ):
        """Test that handle_worktree_merge acquires the merge lock."""
        mock_lock_context = MagicMock()
        mock_merge_lock.return_value = mock_lock_context
        mock_perform.return_value = (True, True)

        agent_item = _make_test_item('test-lock')
        worktree_path = Path('C:/repos/worktrees/task-test-lock')

        success, cleaned = handle_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is True
        assert cleaned is True
        mock_merge_lock.assert_called_once()
        mock_lock_context.__enter__.assert_called_once()
        mock_lock_context.__exit__.assert_called_once()

    @patch('pokepoke.worktree_merge_handler.merge_lock')
    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_handle_merge_passes_through_results(
        self,
        mock_perform,
        mock_merge_lock
    ):
        """Test that handle_worktree_merge passes through perform_worktree_merge results."""
        mock_lock_context = MagicMock()
        mock_merge_lock.return_value = mock_lock_context
        mock_perform.return_value = (False, False)  # Failed merge

        agent_item = _make_test_item('test-passthrough')
        worktree_path = Path('C:/repos/worktrees/task-test-passthrough')

        success, cleaned = handle_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is False
        assert cleaned is False

    @patch('pokepoke.worktree_merge_handler.merge_lock')
    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_handle_merge_releases_lock_on_exception(
        self,
        mock_perform,
        mock_merge_lock
    ):
        """Test that merge lock is released even if exception occurs."""
        mock_lock_context = MagicMock()
        mock_merge_lock.return_value = mock_lock_context
        mock_perform.side_effect = RuntimeError('Test error')

        agent_item = _make_test_item('test-exception')
        worktree_path = Path('C:/repos/worktrees/task-test-exception')

        with pytest.raises(RuntimeError, match='Test error'):
            handle_worktree_merge(
                item_id=agent_item.id,
                item=agent_item,
                worktree_path=worktree_path,
                repo_root=Path('C:/repos'),
                parent_agent_id=None
            )

        # Lock should still be released
        mock_lock_context.__exit__.assert_called_once()


class TestMergeSequenceErrorRecovery:
    """Tests for error recovery during merge sequence."""

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.invoke_cleanup_agent')
    @patch('pokepoke.worktree_merge_handler.merge_worktree')
    def test_retry_after_successful_cleanup(
        self,
        mock_merge,
        mock_invoke_cleanup,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that merge is retried after successful cleanup."""
        # First check fails, second succeeds
        mock_check_ready.side_effect = [
            (False, 'Dirty repo'),
            (True, '')
        ]
        mock_invoke_cleanup.return_value = (True, None)
        mock_merge.return_value = (True, [])
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-retry')
        worktree_path = Path('C:/repos/worktrees/task-test-retry')

        success, cleaned = perform_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        assert success is True
        # Verify both checks were called
        assert mock_check_ready.call_count == 2
        mock_merge.assert_called_once()

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.invoke_cleanup_agent')
    def test_no_retry_if_cleanup_fails(
        self,
        mock_invoke_cleanup,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that merge is not attempted if cleanup fails."""
        mock_check_ready.return_value = (False, 'Dirty repo')
        mock_invoke_cleanup.return_value = (False, None)
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-no-retry')
        worktree_path = Path('C:/repos/worktrees/task-test-no-retry')

        with patch('pokepoke.worktree_merge_handler.merge_worktree') as mock_merge:
            success, cleaned = perform_worktree_merge(
                item_id=agent_item.id,
                item=agent_item,
                worktree_path=worktree_path,
                repo_root=Path('C:/repos'),
                parent_agent_id=None
            )

        assert success is False
        mock_merge.assert_not_called()


class TestCleanupAgentInvocation:
    """Tests for cleanup agent invocation during merge."""

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.invoke_cleanup_agent')
    def test_cleanup_agent_receives_correct_context(
        self,
        mock_invoke_cleanup,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that cleanup agent receives all required context."""
        mock_check_ready.side_effect = [
            (False, 'Dirty repo'),
            (True, '')
        ]
        mock_invoke_cleanup.return_value = (True, None)
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-context')
        worktree_path = Path('C:/repos/worktrees/task-test-context')
        repo_root = Path('C:/repos')
        parent_id = 'parent-agent-123'

        with patch('pokepoke.worktree_merge_handler.merge_worktree', return_value=(True, [])):
            perform_worktree_merge(
                item_id=agent_item.id,
                item=agent_item,
                worktree_path=worktree_path,
                repo_root=repo_root,
                parent_agent_id=parent_id
            )

        # Verify cleanup agent was called with correct parameters
        mock_invoke_cleanup.assert_called_once()
        call_kwargs = mock_invoke_cleanup.call_args[1]
        assert call_kwargs['repo_root'] == repo_root
        assert call_kwargs['parent_agent_id'] == parent_id

    @patch('pokepoke.worktree_merge_handler.cleanup_lock')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.worktree_merge_handler.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.worktree_merge_handler.merge_worktree')
    def test_conflict_agent_receives_conflict_files(
        self,
        mock_merge,
        mock_conflict_agent,
        mock_check_ready,
        mock_cleanup_lock
    ):
        """Test that conflict cleanup agent receives list of conflicted files."""
        mock_check_ready.return_value = (True, '')
        conflict_files = ['src/file1.py', 'src/file2.py', 'tests/test_file.py']
        mock_merge.return_value = (False, conflict_files)
        mock_conflict_agent.return_value = (True, None)
        mock_cleanup_lock.return_value.__enter__ = Mock()
        mock_cleanup_lock.return_value.__exit__ = Mock(return_value=False)

        agent_item = _make_test_item('test-conflicts')
        worktree_path = Path('C:/repos/worktrees/task-test-conflicts')

        perform_worktree_merge(
            item_id=agent_item.id,
            item=agent_item,
            worktree_path=worktree_path,
            repo_root=Path('C:/repos'),
            parent_agent_id=None
        )

        # Verify conflict agent was called
        mock_conflict_agent.assert_called_once()
        call_kwargs = mock_conflict_agent.call_args[1]
        # The conflicted files should be passed in the conflict message
        assert 'file1.py' in str(call_kwargs)
