"""Unit tests for beads integration."""

import subprocess
from unittest.mock import Mock, patch
import json

from pokepoke.beads.beads import get_ready_work_items, get_issue_dependencies, is_item_claimable
from pokepoke.types import BeadsWorkItem


class TestBeadsIntegration:
    """Test beads integration functions."""

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_ready_work_items_empty(self, mock_run: Mock) -> None:
        """Test getting ready work items when none available."""
        mock_run.return_value = Mock(
            stdout="[]",
            returncode=0
        )

        items = get_ready_work_items()

        assert items == []
        mock_run.assert_called_once_with(
            ['ready', '--json']
        )

    @patch('pokepoke.beads.beads_query._run_bd')
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

    @patch('pokepoke.beads.beads_query._run_bd')
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

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_ready_work_items_command_failure(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles subprocess errors gracefully."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ['bd', 'ready', '--json'], stderr="Database not available"
        )

        items = get_ready_work_items()

        assert items == []

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_ready_work_items_timeout(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(
            ['bd', 'ready', '--json'], 30
        )

        items = get_ready_work_items()

        assert items == []

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_ready_work_items_generic_exception(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles generic exceptions gracefully."""
        mock_run.side_effect = RuntimeError("Unexpected error")

        items = get_ready_work_items()

        assert items == []

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_ready_work_items_json_decode_error(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles JSON decode errors gracefully."""
        mock_run.return_value = Mock(
            stdout="invalid json",
            returncode=0
        )

        items = get_ready_work_items()

        assert items == []

    @patch('pokepoke.beads.beads_query._run_bd')
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

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_issue_dependencies_not_found(self, mock_run: Mock) -> None:
        """Test getting dependencies for non-existent issue."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd', stderr="not found")

        result = get_issue_dependencies("nonexistent")

        # Should return None when issue not found
        assert result is None

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_issue_dependencies_empty_result(self, mock_run: Mock) -> None:
        """Test getting dependencies when issue returns empty array."""
        mock_run.return_value = Mock(
            stdout="[]",
            returncode=0
        )

        result = get_issue_dependencies("task-1")

        assert result is None

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_issue_dependencies_no_json_start(self, mock_run: Mock) -> None:
        """Test getting dependencies when no JSON array found."""
        mock_run.return_value = Mock(
            stdout="Note: Some note\nWarning: Some warning",
            returncode=0
        )

        result = get_issue_dependencies("task-1")

        assert result is None

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_ready_work_items_empty_stdout(self, mock_run: Mock) -> None:
        """Test get_ready_work_items returns empty list for empty stdout."""
        mock_run.return_value = Mock(stdout="", returncode=0)

        assert get_ready_work_items() == []

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_ready_work_items_key_error(self, mock_run: Mock) -> None:
        """Test get_ready_work_items handles KeyError from malformed data."""
        mock_run.return_value = Mock(stdout='[{"unexpected": "data"}]', returncode=0)

        assert get_ready_work_items() == []

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_issue_dependencies_empty_stdout(self, mock_run: Mock) -> None:
        """Test get_issue_dependencies returns None for empty stdout."""
        mock_run.return_value = Mock(stdout="", returncode=0)

        assert get_issue_dependencies("task-1") is None

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_has_unmet_blocking_dependencies_no_blockers(self, mock_run: Mock) -> None:
        """Test has_unmet_blocking_dependencies returns False with no blockers."""
        from pokepoke.beads.beads import has_unmet_blocking_dependencies

        mock_run.return_value = Mock(
            stdout=json.dumps([{
                "id": "task-1", "title": "T", "status": "open",
                "priority": 1, "issue_type": "task",
                "dependencies": [{"id": "dep-1", "title": "D",
                                  "dependency_type": "blocks", "status": "closed",
                                  "issue_type": "task", "priority": 1}]
            }]),
            returncode=0
        )

        assert has_unmet_blocking_dependencies("task-1") is False

    @patch('pokepoke.beads.beads_query._run_bd')
    def test_has_unmet_blocking_dependencies_with_blocker(self, mock_run: Mock) -> None:
        """Test has_unmet_blocking_dependencies returns True with open blocker."""
        from pokepoke.beads.beads import has_unmet_blocking_dependencies

        mock_run.return_value = Mock(
            stdout=json.dumps([{
                "id": "task-1", "title": "T", "status": "open",
                "priority": 1, "issue_type": "task",
                "dependencies": [{"id": "dep-1", "title": "D",
                                  "dependency_type": "blocks", "status": "open",
                                  "issue_type": "task", "priority": 1}]
            }]),
            returncode=0
        )

        assert has_unmet_blocking_dependencies("task-1") is True


class TestHasFeatureParent:
    """Test has_feature_parent function."""

    @patch('pokepoke.beads.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_true(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent returns True when parent is feature."""
        from pokepoke.beads.beads import has_feature_parent
        from pokepoke.types import IssueWithDependencies, Dependency

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

    @patch('pokepoke.beads.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_false_no_dependencies(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent returns False when no dependencies."""
        from pokepoke.beads.beads import has_feature_parent
        from pokepoke.types import IssueWithDependencies

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

    @patch('pokepoke.beads.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_false_non_parent_dependency(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent returns False for non-parent dependencies."""
        from pokepoke.beads.beads import has_feature_parent
        from pokepoke.types import IssueWithDependencies, Dependency

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

    @patch('pokepoke.beads.beads_hierarchy.get_issue_dependencies')
    def test_has_feature_parent_error_handling(self, mock_get_issue: Mock) -> None:
        """Test has_feature_parent handles errors gracefully."""
        from pokepoke.beads.beads import has_feature_parent

        mock_get_issue.side_effect = Exception("Network error")

        result = has_feature_parent("task-1")

        assert result is False


class TestIsItemClaimable:
    """Test is_item_claimable function."""

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_unassigned_item_claimable(self, mock_run: Mock) -> None:
        """Test that unassigned item is claimable."""
        mock_run.return_value = Mock(
            stdout=json.dumps([{"id": "task-1", "assignee": "", "status": "open"}]),
            returncode=0
        )

        result = is_item_claimable("task-1")

        assert result is True

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assigned_item_not_claimable(self, mock_run: Mock) -> None:
        """Test that item assigned to another agent is not claimable."""
        mock_run.return_value = Mock(
            stdout=json.dumps([{"id": "task-1", "assignee": "other-agent", "status": "in_progress"}]),
            returncode=0
        )

        result = is_item_claimable("task-1")

        assert result is False

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_no_assignee_field_claimable(self, mock_run: Mock) -> None:
        """Test item with missing assignee field is claimable."""
        mock_run.return_value = Mock(
            stdout=json.dumps([{"id": "task-1", "status": "open"}]),
            returncode=0
        )

        result = is_item_claimable("task-1")

        assert result is True

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_subprocess_error_not_claimable(self, mock_run: Mock) -> None:
        """Test that subprocess errors return not claimable (safe default)."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd', stderr="error")

        result = is_item_claimable("task-1")

        assert result is False

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_json_decode_error_not_claimable(self, mock_run: Mock) -> None:
        """Test that JSON decode errors return not claimable (safe default)."""
        mock_run.return_value = Mock(stdout="invalid json", returncode=0)

        result = is_item_claimable("task-1")

        assert result is False

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_none_parse_result_not_claimable(self, mock_run: Mock) -> None:
        """Test that None parse result returns not claimable."""
        mock_run.return_value = Mock(stdout="", returncode=0)

        result = is_item_claimable("task-1")

        assert result is False


class TestAssignAndSyncItem:
    """Test assign_and_sync_item race condition detection."""

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_unassigned_item_success(self, mock_run: Mock, mock_sync: Mock) -> None:
        """Test successfully assigning an unassigned item."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-success"

        # Mock bd show returns unassigned item
        show_result = Mock(
            stdout=json.dumps([{"id": item_id, "owner": "", "status": "open"}]),
            returncode=0
        )

        # Mock bd update succeeds
        update_result = Mock(returncode=0)

        # Mock post-claim verify show returns item assigned to us
        verify_show_result = Mock(
            stdout=json.dumps([{"id": item_id, "assignee": "test-agent", "status": "in_progress"}]),
            returncode=0
        )

        mock_sync.return_value = Mock(returncode=0)
        mock_run.side_effect = [show_result, update_result, verify_show_result]

        result = assign_and_sync_item(item_id, "test-agent")

        assert result is True
        assert mock_run.call_count == 3
        mock_sync.assert_called_once()

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_detects_race_condition(self, mock_run: Mock) -> None:
        """Test detection of race condition when another agent claimed item."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-race"

        # Mock bd show returns item assigned to OTHER agent (via assignee field)
        show_result = Mock(
            stdout=json.dumps([{
                "id": item_id,
                "assignee": "other-agent",  # CRITICAL: assignee field, not owner!
                "status": "in_progress"
            }]),
            returncode=0
        )

        mock_run.return_value = show_result

        result = assign_and_sync_item(item_id, "my-agent")

        # Should detect race condition and return False
        assert result is False
        # Should only call bd show, NOT bd update
        assert mock_run.call_count == 1

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_claim_verification_detects_stolen_claim(self, mock_run: Mock) -> None:
        """Test that we abort if post-claim verification shows another assignee."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-verify"

        show_result = Mock(
            stdout=json.dumps([{"id": item_id, "owner": "", "status": "open"}]),
            returncode=0
        )
        update_result = Mock(returncode=0)
        verify_show_result = Mock(
            stdout=json.dumps([{"id": item_id, "assignee": "other-agent", "status": "in_progress"}]),
            returncode=0
        )

        mock_run.side_effect = [show_result, update_result, verify_show_result]

        result = assign_and_sync_item(item_id, "agent-1")

        assert result is False
        assert mock_run.call_count == 3

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_allows_claiming_own_item(self, mock_run: Mock) -> None:
        """Test that agent can update items already assigned to them."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-own"

        # Mock bd show returns item already assigned to THIS agent
        show_result = Mock(
            stdout=json.dumps([{
                "id": item_id,
                "assignee": "my-agent",
                "status": "in_progress"
            }]),
            returncode=0
        )

        # Mock bd update succeeds
        update_result = Mock(returncode=0)

        verify_show_result = Mock(
            stdout=json.dumps([{"id": item_id, "assignee": "my-agent", "status": "in_progress"}]),
            returncode=0
        )

        # Mock bd sync succeeds
        sync_result = Mock(returncode=0)

        mock_run.side_effect = [show_result, update_result, verify_show_result, sync_result]

        result = assign_and_sync_item(item_id, "my-agent")

        # Item already assigned to my-agent and in_progress — early return after show
        assert result is True
        assert mock_run.call_count == 1

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_allows_claiming_by_username(self, mock_run: Mock, mock_sync: Mock) -> None:
        """Test that agent can claim unassigned items owned by a human user."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-owned"

        # Owned by a human (owner field), but not assigned to any agent.
        show_result = Mock(
            stdout=json.dumps([{
                "id": item_id,
                "owner": "ameliapayne@microsoft.com",
                "status": "open"
            }]),
            returncode=0
        )

        update_result = Mock(returncode=0)
        verify_show_result = Mock(
            stdout=json.dumps([{"id": item_id, "assignee": "agent-1", "status": "in_progress"}]),
            returncode=0
        )

        mock_sync.return_value = Mock(returncode=0)
        mock_run.side_effect = [show_result, update_result, verify_show_result]

        result = assign_and_sync_item(item_id, "agent-1")

        assert result is True
        assert mock_run.call_count == 3

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_handles_show_failure(self, mock_run: Mock) -> None:
        """Test handling of bd show command failure."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-show-fail"

        # Mock bd show fails
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd', stderr="not found")

        result = assign_and_sync_item(item_id, "agent-1")

        # Should return False on verification failure
        assert result is False

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_handles_update_failure(self, mock_run: Mock) -> None:
        """Test handling of bd update command failure."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-update-fail"

        # Mock bd show succeeds (unassigned)
        show_result = Mock(
            stdout=json.dumps([{"id": item_id, "owner": "", "status": "open"}]),
            returncode=0
        )

        # Mock bd update fails
        update_failure = subprocess.CalledProcessError(1, 'bd', stderr="update failed")

        mock_run.side_effect = [show_result, update_failure]

        result = assign_and_sync_item(item_id, "agent-1")

        # Should return False on update failure
        assert result is False

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_handles_json_parse_error(self, mock_run: Mock) -> None:
        """Test handling of malformed JSON from bd show."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-json-error"

        # Mock bd show returns invalid JSON (has { but malformed)
        show_result = Mock(
            stdout='{"id": "task-1", "owner": INVALID}',
            returncode=0
        )

        mock_run.return_value = show_result

        result = assign_and_sync_item(item_id, "agent-1")

        # Should return False on parse error
        assert result is False

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_sync_failure_still_succeeds(self, mock_run: Mock, mock_sync: Mock) -> None:
        """Test that assignment succeeds even if sync fails."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-sync-failure"

        show_result = Mock(
            stdout=json.dumps([{"id": item_id, "owner": "", "status": "open"}]),
            returncode=0
        )
        update_result = Mock(returncode=0)
        verify_show_result = Mock(
            stdout=json.dumps([{"id": item_id, "assignee": "agent-1", "status": "in_progress"}]),
            returncode=0
        )

        # Mock bd sync fails (non-zero return)
        mock_sync.return_value = Mock(returncode=1, stdout='', stderr='sync error')
        mock_run.side_effect = [show_result, update_result, verify_show_result]

        result = assign_and_sync_item(item_id, "agent-1")

        assert result is True

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_sync_retries_on_access_denied(self, mock_run: Mock, mock_sync: Mock) -> None:
        """Test that sync is called after successful claim."""
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-sync-retry"

        show_result = Mock(
            stdout=json.dumps([{"id": item_id, "owner": "", "status": "open"}]),
            returncode=0
        )
        update_result = Mock(returncode=0)
        verify_show_result = Mock(
            stdout=json.dumps([{"id": item_id, "assignee": "agent-1", "status": "in_progress"}]),
            returncode=0
        )

        mock_sync.return_value = Mock(returncode=0)
        mock_run.side_effect = [show_result, update_result, verify_show_result]

        result = assign_and_sync_item(item_id, "agent-1")

        assert result is True
        assert mock_run.call_count == 3
        mock_sync.assert_called_once()

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_assign_defaults_agent_name_from_env(self, mock_run: Mock, mock_sync: Mock) -> None:
        """Test that assign_and_sync_item uses AGENT_NAME env var when agent_name is None."""
        import os
        from pokepoke.beads.beads import assign_and_sync_item

        item_id = "task-assign-env-default"

        show_result = Mock(
            stdout=json.dumps([{"id": item_id, "owner": "", "status": "open"}]),
            returncode=0
        )
        update_result = Mock(returncode=0)
        verify_show_result = Mock(
            stdout=json.dumps([{"id": item_id, "assignee": "env_agent", "status": "in_progress"}]),
            returncode=0
        )
        mock_sync.return_value = Mock(returncode=0)
        mock_run.side_effect = [show_result, update_result, verify_show_result]

        old_val = os.environ.get('AGENT_NAME')
        os.environ['AGENT_NAME'] = 'env_agent'
        try:
            result = assign_and_sync_item(item_id)
            assert result is True
        finally:
            if old_val is not None:
                os.environ['AGENT_NAME'] = old_val
            else:
                os.environ.pop('AGENT_NAME', None)


class TestCloseItem:
    """Test close_item function."""

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_close_item_success(self, mock_run: Mock) -> None:
        """Test successful item closing."""
        from pokepoke.beads.beads import close_item

        mock_run.return_value = Mock(returncode=0)

        result = close_item("task-1", "Done")

        assert result is True
        mock_run.assert_called_once_with(
            ['close', 'task-1', '--reason', 'Done']
        )

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_close_item_failure(self, mock_run: Mock) -> None:
        """Test close_item returns False on failure."""
        from pokepoke.beads.beads import close_item

        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'bd', stderr="Item not found"
        )

        result = close_item("task-999")

        assert result is False


class TestAddComment:
    """Test add_comment function."""

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_add_comment_success(self, mock_run: Mock) -> None:
        """Test successful comment addition."""
        from pokepoke.beads.beads import add_comment

        mock_run.return_value = Mock(returncode=0)

        result = add_comment("task-1", "Great progress")

        assert result is True
        mock_run.assert_called_once_with(
            ['comments', 'add', 'task-1', 'Great progress']
        )

    @patch('pokepoke.beads.beads_management._run_bd')
    def test_add_comment_failure(self, mock_run: Mock) -> None:
        """Test add_comment returns False on failure."""
        from pokepoke.beads.beads import add_comment

        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'bd', stderr="Error"
        )

        result = add_comment("task-1", "comment")

        assert result is False


class TestSelectNextHierarchicalItem:
    """Test select_next_hierarchical_item function."""

    def test_empty_list_returns_none(self) -> None:
        """Test empty list returns None."""
        from pokepoke.beads.beads import select_next_hierarchical_item

        result = select_next_hierarchical_item([])

        assert result is None

    @patch('pokepoke.beads.beads_management.resolve_to_leaf_task')
    def test_epic_resolved_to_leaf(self, mock_resolve: Mock) -> None:
        """Test epic is resolved to leaf task."""
        from pokepoke.beads.beads import select_next_hierarchical_item

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

    @patch('pokepoke.beads.beads_management.resolve_to_leaf_task')
    def test_epic_unresolvable_skipped(self, mock_resolve: Mock) -> None:
        """Test epic that can't be resolved is skipped."""
        from pokepoke.beads.beads import select_next_hierarchical_item

        epic = BeadsWorkItem(
            id="epic-1", title="Epic", description="",
            status="open", priority=1, issue_type="epic"
        )
        mock_resolve.return_value = None

        result = select_next_hierarchical_item([epic])

        assert result is None


class TestUnassignItem:
    """Test unassign_item function."""

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_unassign_success(self, mock_run: Mock, mock_sync: Mock) -> None:
        """Test successful unassign resets item to new and syncs."""
        from pokepoke.beads.beads import unassign_item

        mock_run.return_value = Mock(returncode=0, stderr='')
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("task-1")

        assert result is True
        # First call should try status open + clear assignee
        mock_run.assert_called_once_with(
            ['update', 'task-1', '--status', 'open', '-a', '']
        )
        mock_sync.assert_called_once()

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_unassign_falls_back_when_empty_assignee_unsupported(
        self, mock_run: Mock, mock_sync: Mock
    ) -> None:
        """Test fallback to status-only reset when -a '' is not supported."""
        from pokepoke.beads.beads import unassign_item

        # First call (with -a '') raises; second call (without -a) succeeds.
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, 'bd', stderr="invalid option"),
            Mock(returncode=0, stderr=''),
        ]
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("task-1")

        assert result is True
        assert mock_run.call_count == 2
        # Second call should omit the -a argument
        mock_run.assert_called_with(
            ['update', 'task-1', '--status', 'open']
        )
        mock_sync.assert_called_once()

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_unassign_returns_false_when_both_commands_fail(
        self, mock_run: Mock, mock_sync: Mock
    ) -> None:
        """Test unassign_item returns False when bd update fails entirely."""
        from pokepoke.beads.beads import unassign_item

        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd', stderr="error")
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("task-1")

        assert result is False
        mock_sync.assert_not_called()

    @patch('pokepoke.beads.beads_management.run_bd_sync_with_retry')
    @patch('pokepoke.beads.beads_management._run_bd')
    def test_unassign_returns_true_even_when_sync_fails(
        self, mock_run: Mock, mock_sync: Mock
    ) -> None:
        """Test unassign_item returns True (best-effort) even when sync fails."""
        from pokepoke.beads.beads import unassign_item

        mock_run.return_value = Mock(returncode=0, stderr='')
        mock_sync.return_value = Mock(returncode=1, stdout='', stderr='sync error')

        result = unassign_item("task-1")

        # Status was reset successfully; sync failure is non-fatal
        assert result is True
        mock_sync.assert_called_once()
