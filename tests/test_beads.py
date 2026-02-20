"""Unit tests for beads integration."""

import subprocess
from unittest.mock import Mock, patch
import json

from src.pokepoke.beads import get_ready_work_items, get_issue_dependencies
from src.pokepoke.types import BeadsWorkItem


class TestBeadsIntegration:
    """Test beads integration functions."""

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_ready_work_items_empty(self, mock_run: Mock) -> None:
        """Test getting ready work items when none available."""
        mock_run.return_value = Mock(
            stdout="[]",
            returncode=0
        )

        items = get_ready_work_items()

        assert items == []
        mock_run.assert_called_once_with(
            ['bd', 'ready', '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30
        )

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_ready_work_items_with_items(self, mock_run: Mock) -> None:
        """Test getting ready work items with results."""
        mock_data = [
            {
                "id": "test-123",
                "title": "Test task",
                "issue_type": "task",
                "status": "open",
                "priority": 1,
                "description": ""
            }
        ]
        mock_run.return_value = Mock(
            stdout=json.dumps(mock_data),
            returncode=0
        )

        items = get_ready_work_items()

        assert len(items) == 1
        assert items[0].id == "test-123"
        assert items[0].title == "Test task"
        assert items[0].priority == 1

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_ready_work_items_filters_warnings(self, mock_run: Mock) -> None:
        """Test that warning/note lines are filtered out."""
        mock_data = [{"id": "test-123", "title": "Test", "issue_type": "task", "status": "open", "priority": 1, "description": ""}]
        mock_output = f"Note: Some note\nWarning: Some warning\n{json.dumps(mock_data)}"
        mock_run.return_value = Mock(
            stdout=mock_output,
            returncode=0
        )

        items = get_ready_work_items()

        assert len(items) == 1
        assert items[0].id == "test-123"

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_ready_work_items_command_failure(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles subprocess errors gracefully."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ['bd', 'ready', '--json'], stderr="Database not available"
        )

        items = get_ready_work_items()

        assert items == []

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_ready_work_items_timeout(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            ['bd', 'ready', '--json'], 30
        )

        items = get_ready_work_items()

        assert items == []

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_ready_work_items_generic_exception(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles generic exceptions gracefully."""
        mock_run.side_effect = RuntimeError("Unexpected error")

        items = get_ready_work_items()

        assert items == []

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_ready_work_items_json_decode_error(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles JSON decode errors gracefully."""
        mock_run.return_value = Mock(
            stdout="invalid json",
            returncode=0
        )

        items = get_ready_work_items()

        assert items == []

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_issue_dependencies_found(self, mock_run: Mock) -> None:
        """Test getting issue dependencies when issue exists."""
        mock_data = [{
            "id": "task-1",
            "title": "Task",
            "description": "Description",
            "status": "open",
            "priority": 1,
            "issue_type": "task",
            "dependencies": [
                {
                    "id": "feature-1",
                    "title": "Feature",
                    "issue_type": "feature",
                    "dependency_type": "parent",
                    "status": "open",
                    "priority": 1
                }
            ],
            "dependents": [
                {
                    "id": "subtask-1",
                    "title": "Subtask",
                    "issue_type": "task",
                    "dependency_type": "parent",
                    "status": "open",
                    "priority": 2
                }
            ]
        }]
        mock_run.return_value = Mock(
            stdout=json.dumps(mock_data),
            returncode=0
        )

        result = get_issue_dependencies("task-1")

        assert result is not None
        assert result.id == "task-1"
        assert len(result.dependencies) == 1
        assert result.dependencies[0].id == "feature-1"
        assert len(result.dependents) == 1
        assert result.dependents[0].id == "subtask-1"

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_issue_dependencies_not_found(self, mock_run: Mock) -> None:
        """Test getting dependencies for non-existent issue."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd', stderr="not found")

        result = get_issue_dependencies("nonexistent")

        # Should return None when issue not found
        assert result is None

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_issue_dependencies_empty_result(self, mock_run: Mock) -> None:
        """Test getting dependencies when issue returns empty array."""
        mock_run.return_value = Mock(
            stdout="[]",
            returncode=0
        )

        result = get_issue_dependencies("task-1")

        assert result is None

    @patch('src.pokepoke.beads_query.subprocess.run')
    def test_get_issue_dependencies_no_json_start(self, mock_run: Mock) -> None:
        """Test getting dependencies when no JSON array found."""
        mock_run.return_value = Mock(
            stdout="Note: Some note\nWarning: Some warning",
            returncode=0
        )

        result = get_issue_dependencies("task-1")

        assert result is None


class TestHasFeatureParent:
    """Test has_feature_parent function."""

    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_true(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent returns True when parent is feature."""
        from src.pokepoke.beads import has_feature_parent
        from src.pokepoke.types import IssueWithDependencies, Dependency

        mock_get_issue.return_value = IssueWithDependencies(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="feature-1",
                    title="Feature",
                    issue_type="feature",
                    dependency_type="parent",
                    status="open",
                    priority=1
                )
            ]
        )

        result = has_feature_parent("task-1")

        assert result is True

    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_false_no_dependencies(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent returns False when no dependencies."""
        from src.pokepoke.beads import has_feature_parent
        from src.pokepoke.types import IssueWithDependencies

        mock_get_issue.return_value = IssueWithDependencies(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=None
        )

        result = has_feature_parent("task-1")

        assert result is False

    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_false_non_parent_dependency(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent returns False for non-parent dependencies."""
        from src.pokepoke.beads import has_feature_parent
        from src.pokepoke.types import IssueWithDependencies, Dependency

        mock_get_issue.return_value = IssueWithDependencies(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="task-2",
                    title="Related Task",
                    issue_type="task",
                    dependency_type="blocks",
                    status="open",
                    priority=1
                )
            ]
        )

        result = has_feature_parent("task-1")

        assert result is False

    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_error_handling(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent handles errors gracefully."""
        from src.pokepoke.beads import has_feature_parent

        mock_get_issue.side_effect = Exception("Network error")

        result = has_feature_parent("task-1")

        assert result is False


class TestAssignAndSyncItem:
    """Test assign_and_sync_item race condition detection."""

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_unassigned_item_success(self, mock_run: Mock) -> None:
        """Test successfully assigning an unassigned item."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show returns unassigned item
        show_result = Mock(
            stdout=json.dumps([{"id": "task-1", "owner": "", "status": "open"}]),
            returncode=0
        )

        # Mock bd update succeeds
        update_result = Mock(returncode=0)

        # Mock bd sync succeeds
        sync_result = Mock(returncode=0)

        mock_run.side_effect = [show_result, update_result, sync_result]

        result = assign_and_sync_item("task-1", "test-agent")

        assert result is True
        assert mock_run.call_count == 3

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_detects_race_condition(self, mock_run: Mock) -> None:
        """Test detection of race condition when another agent claimed item."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show returns item assigned to OTHER agent (via assignee field)
        show_result = Mock(
            stdout=json.dumps([{
                "id": "task-1",
                "assignee": "other-agent",  # CRITICAL: assignee field, not owner!
                "status": "in_progress"
            }]),
            returncode=0
        )

        mock_run.return_value = show_result

        result = assign_and_sync_item("task-1", "my-agent")

        # Should detect race condition and return False
        assert result is False
        # Should only call bd show, NOT bd update
        assert mock_run.call_count == 1

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_allows_claiming_own_item(self, mock_run: Mock) -> None:
        """Test that agent can update items already assigned to them."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show returns item already assigned to THIS agent
        show_result = Mock(
            stdout=json.dumps([{
                "id": "task-1",
                "owner": "my-agent",
                "status": "in_progress"
            }]),
            returncode=0
        )

        # Mock bd update succeeds
        update_result = Mock(returncode=0)

        # Mock bd sync succeeds
        sync_result = Mock(returncode=0)

        mock_run.side_effect = [show_result, update_result, sync_result]

        result = assign_and_sync_item("task-1", "my-agent")

        # Should allow updating own item
        assert result is True
        assert mock_run.call_count == 3

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_allows_claiming_by_username(self, mock_run: Mock) -> None:
        """Test that agent can claim items assigned to their username."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show returns item assigned to username (email format)
        show_result = Mock(
            stdout=json.dumps([{
                "id": "task-1",
                "owner": "ameliapayne@microsoft.com",
                "status": "in_progress"
            }]),
            returncode=0
        )

        # Mock bd update succeeds
        update_result = Mock(returncode=0)

        # Mock bd sync succeeds
        sync_result = Mock(returncode=0)

        mock_run.side_effect = [show_result, update_result, sync_result]

        result = assign_and_sync_item("task-1", "agent-1")

        # Should allow claiming item assigned to username in email
        assert result is True
        assert mock_run.call_count == 3

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_handles_show_failure(self, mock_run: Mock) -> None:
        """Test handling of bd show command failure."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show fails
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd', stderr="not found")

        result = assign_and_sync_item("task-1", "agent-1")

        # Should return False on verification failure
        assert result is False

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_handles_update_failure(self, mock_run: Mock) -> None:
        """Test handling of bd update command failure."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show succeeds (unassigned)
        show_result = Mock(
            stdout=json.dumps([{"id": "task-1", "owner": "", "status": "open"}]),
            returncode=0
        )

        # Mock bd update fails
        update_failure = subprocess.CalledProcessError(1, 'bd', stderr="update failed")

        mock_run.side_effect = [show_result, update_failure]

        result = assign_and_sync_item("task-1", "agent-1")

        # Should return False on update failure
        assert result is False

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_handles_json_parse_error(self, mock_run: Mock) -> None:
        """Test handling of malformed JSON from bd show."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show returns invalid JSON (has { but malformed)
        show_result = Mock(
            stdout='{"id": "task-1", "owner": INVALID}',
            returncode=0
        )

        mock_run.return_value = show_result

        result = assign_and_sync_item("task-1", "agent-1")

        # Should return False on parse error
        assert result is False

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_sync_failure_still_succeeds(self, mock_run: Mock) -> None:
        """Test that assignment succeeds even if sync fails."""
        from src.pokepoke.beads import assign_and_sync_item

        # Mock bd show returns unassigned
        show_result = Mock(
            stdout=json.dumps([{"id": "task-1", "owner": "", "status": "open"}]),
            returncode=0
        )

        # Mock bd update succeeds
        update_result = Mock(returncode=0)

        # Mock bd sync fails (non-zero return)
        sync_result = Mock(returncode=1)

        mock_run.side_effect = [show_result, update_result, sync_result]

        result = assign_and_sync_item("task-1", "agent-1")

        # Should still return True - assignment succeeded even if sync failed
        assert result is True

    @patch('src.pokepoke.beads_management.time.sleep')
    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_sync_retries_on_access_denied(self, mock_run: Mock, mock_sleep: Mock) -> None:
        """Test that sync retries when JSONL file is locked."""
        from src.pokepoke.beads import assign_and_sync_item

        show_result = Mock(
            stdout=json.dumps([{"id": "task-1", "owner": "", "status": "open"}]),
            returncode=0
        )
        update_result = Mock(returncode=0)
        sync_failure = Mock(
            returncode=1,
            stdout="",
            stderr="failed to replace JSONL file: rename issues.jsonl.tmp issues.jsonl: Access is denied."
        )
        sync_success = Mock(returncode=0)

        mock_run.side_effect = [show_result, update_result, sync_failure, sync_success]

        result = assign_and_sync_item("task-1", "agent-1")

        assert result is True
        assert mock_run.call_count == 4
        mock_sleep.assert_called_once()

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_assign_defaults_agent_name_from_env(self, mock_run: Mock) -> None:
        """Test that assign_and_sync_item uses AGENT_NAME env var when agent_name is None."""
        import os
        from src.pokepoke.beads import assign_and_sync_item

        show_result = Mock(
            stdout=json.dumps([{"id": "task-1", "owner": "", "status": "open"}]),
            returncode=0
        )
        update_result = Mock(returncode=0)
        sync_result = Mock(returncode=0)
        mock_run.side_effect = [show_result, update_result, sync_result]

        old_val = os.environ.get('AGENT_NAME')
        os.environ['AGENT_NAME'] = 'env_agent'
        try:
            result = assign_and_sync_item("task-1")
            assert result is True
        finally:
            if old_val is not None:
                os.environ['AGENT_NAME'] = old_val
            else:
                os.environ.pop('AGENT_NAME', None)


class TestCloseItem:
    """Test close_item function."""

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_close_item_success(self, mock_run: Mock) -> None:
        """Test successful item closing."""
        from src.pokepoke.beads import close_item

        mock_run.return_value = Mock(returncode=0)

        result = close_item("task-1", "Done")

        assert result is True
        mock_run.assert_called_once_with(
            ['bd', 'close', 'task-1', '--reason', 'Done'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30
        )

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_close_item_failure(self, mock_run: Mock) -> None:
        """Test close_item returns False on failure."""
        from src.pokepoke.beads import close_item

        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'bd', stderr="Item not found"
        )

        result = close_item("task-999")

        assert result is False


class TestAddComment:
    """Test add_comment function."""

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_add_comment_success(self, mock_run: Mock) -> None:
        """Test successful comment addition."""
        from src.pokepoke.beads import add_comment

        mock_run.return_value = Mock(returncode=0)

        result = add_comment("task-1", "Great progress")

        assert result is True
        mock_run.assert_called_once_with(
            ['bd', 'comments', 'add', 'task-1', 'Great progress'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30
        )

    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_add_comment_failure(self, mock_run: Mock) -> None:
        """Test add_comment returns False on failure."""
        from src.pokepoke.beads import add_comment

        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'bd', stderr="Error"
        )

        result = add_comment("task-1", "comment")

        assert result is False


class TestSelectNextHierarchicalItem:
    """Test select_next_hierarchical_item function."""

    def test_empty_list_returns_none(self) -> None:
        """Test empty list returns None."""
        from src.pokepoke.beads import select_next_hierarchical_item

        result = select_next_hierarchical_item([])

        assert result is None

    @patch('src.pokepoke.beads_management.resolve_to_leaf_task')
    def test_epic_resolved_to_leaf(self, mock_resolve: Mock) -> None:
        """Test epic is resolved to leaf task."""
        from src.pokepoke.beads import select_next_hierarchical_item

        leaf = BeadsWorkItem(
            id="task-child", title="Child", description="",
            status="open", priority=1, issue_type="task"
        )
        epic = BeadsWorkItem(
            id="epic-1", title="Epic", description="",
            status="open", priority=1, issue_type="epic"
        )
        mock_resolve.return_value = leaf

        result = select_next_hierarchical_item([epic])

        assert result == leaf

    @patch('src.pokepoke.beads_management.resolve_to_leaf_task')
    def test_epic_unresolvable_skipped(self, mock_resolve: Mock) -> None:
        """Test epic that can't be resolved is skipped."""
        from src.pokepoke.beads import select_next_hierarchical_item

        epic = BeadsWorkItem(
            id="epic-1", title="Epic", description="",
            status="open", priority=1, issue_type="epic"
        )
        mock_resolve.return_value = None

        result = select_next_hierarchical_item([epic])

        assert result is None


class TestUnassignItem:
    """Test unassign_item function."""

    @patch('src.pokepoke.beads_management.run_bd_sync_with_retry')
    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_unassign_success(self, mock_run: Mock, mock_sync: Mock) -> None:
        """Test successful unassign resets item to new and syncs."""
        from src.pokepoke.beads import unassign_item

        mock_run.return_value = Mock(returncode=0)
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("task-1")

        assert result is True
        # First call should try status new + clear assignee
        mock_run.assert_called_once_with(
            ['bd', 'update', 'task-1', '--status', 'new', '-a', ''],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30,
        )
        mock_sync.assert_called_once()

    @patch('src.pokepoke.beads_management.run_bd_sync_with_retry')
    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_unassign_falls_back_when_empty_assignee_unsupported(
        self, mock_run: Mock, mock_sync: Mock
    ) -> None:
        """Test fallback to status-only reset when -a '' is not supported."""
        from src.pokepoke.beads import unassign_item

        # First call (with -a '') raises; second call (without -a) succeeds.
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'bd', stderr="invalid option"),
            Mock(returncode=0),
        ]
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("task-1")

        assert result is True
        assert mock_run.call_count == 2
        # Second call should omit the -a argument
        mock_run.assert_called_with(
            ['bd', 'update', 'task-1', '--status', 'new'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30,
        )
        mock_sync.assert_called_once()

    @patch('src.pokepoke.beads_management.run_bd_sync_with_retry')
    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_unassign_returns_false_when_both_commands_fail(
        self, mock_run: Mock, mock_sync: Mock
    ) -> None:
        """Test unassign_item returns False when bd update fails entirely."""
        from src.pokepoke.beads import unassign_item

        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd', stderr="error")
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("task-1")

        assert result is False
        mock_sync.assert_not_called()

    @patch('src.pokepoke.beads_management.run_bd_sync_with_retry')
    @patch('src.pokepoke.beads_management.subprocess.run')
    def test_unassign_returns_true_even_when_sync_fails(
        self, mock_run: Mock, mock_sync: Mock
    ) -> None:
        """Test unassign_item returns True (best-effort) even when sync fails."""
        from src.pokepoke.beads import unassign_item

        mock_run.return_value = Mock(returncode=0)
        mock_sync.return_value = Mock(returncode=1, stdout='', stderr='sync error')

        result = unassign_item("task-1")

        # Status was reset successfully; sync failure is non-fatal
        assert result is True
        mock_sync.assert_called_once()
