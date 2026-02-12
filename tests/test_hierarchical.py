"""Unit tests for hierarchical work assignment."""

import subprocess
from unittest.mock import Mock, patch, call
import json
import pytest

from pokepoke.beads import (
    get_children,
    get_next_child_task,
    all_children_complete,
    close_parent_if_complete,
    select_next_hierarchical_item,
    get_parent_id,
    close_item,
    resolve_to_leaf_task
)
from pokepoke.types import BeadsWorkItem, IssueWithDependencies, Dependency


class TestHierarchicalWorkAssignment:
    """Test hierarchical work assignment functions."""
    
    @patch('pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_get_children_no_dependents(self, mock_get_issue: Mock) -> None:
        """Test getting children when issue has no dependents."""
        mock_get_issue.return_value = IssueWithDependencies(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic",
            dependents=None
        )
        
        children = get_children("epic-1")
        
        assert children == []
    
    @patch('pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_get_children_with_parent_dependents(self, mock_get_issue: Mock) -> None:
        """Test getting children with parent-type dependents."""
        # Mock parent issue
        mock_get_issue.side_effect = [
            IssueWithDependencies(
                id="epic-1",
                title="Epic",
                description="",
                status="open",
                priority=1,
                issue_type="epic",
                dependents=[
                    Dependency(
                        id="task-1",
                        title="Task 1",
                        issue_type="task",
                        dependency_type="parent",
                        status="open",
                        priority=1
                    )
                ]
            ),
            # Mock child issue details
            IssueWithDependencies(
                id="task-1",
                title="Task 1",
                description="Task description",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        
        children = get_children("epic-1")
        
        assert len(children) == 1
        assert children[0].id == "task-1"
        assert children[0].title == "Task 1"
        assert children[0].issue_type == "task"
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_get_next_child_task_no_children(self, mock_get_children: Mock) -> None:
        """Test getting next child when there are no children."""
        mock_get_children.return_value = []
        
        next_child = get_next_child_task("epic-1")
        
        assert next_child is None
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_get_next_child_task_all_complete(self, mock_get_children: Mock) -> None:
        """Test getting next child when all children are complete."""
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="done",
                priority=1,
                issue_type="task"
            )
        ]
        
        next_child = get_next_child_task("epic-1")
        
        assert next_child is None
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_get_next_child_task_returns_highest_priority(self, mock_get_children: Mock) -> None:
        """Test that next child returns highest priority open task."""
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Low priority",
                description="",
                status="open",
                priority=3,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-2",
                title="High priority",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-3",
                title="Medium priority",
                description="",
                status="open",
                priority=2,
                issue_type="task"
            )
        ]
        
        next_child = get_next_child_task("epic-1")
        
        assert next_child is not None
        assert next_child.id == "task-2"
        assert next_child.priority == 1
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_get_next_child_task_skips_items_assigned_to_others(self, mock_get_children: Mock) -> None:
        """Test that next child skips items assigned to other agents."""
        # Set up current agent
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'
        
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="High priority but assigned to other agent",
                description="",
                status="in_progress",
                priority=1,
                issue_type="task",
                owner="agent_beta"  # Assigned to different agent
            ),
            BeadsWorkItem(
                id="task-2",
                title="Lower priority but available",
                description="",
                status="open",
                priority=2,
                issue_type="task",
                owner=None  # Unassigned
            ),
            BeadsWorkItem(
                id="task-3",
                title="Assigned to current agent",
                description="",
                status="in_progress",
                priority=3,
                issue_type="task",
                owner="agent_alpha"  # Assigned to us
            )
        ]
        
        next_child = get_next_child_task("epic-1")
        
        # Should return task-2 (unassigned, priority 2) because task-1 is assigned to someone else
        # Even though task-3 is assigned to us, task-2 has higher priority
        assert next_child is not None
        assert next_child.id == "task-2"
        assert next_child.priority == 2
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_get_next_child_task_all_assigned_to_others(self, mock_get_children: Mock) -> None:
        """Test that next child returns None when all items are assigned to other agents."""
        # Set up current agent
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'
        
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Assigned to agent beta",
                description="",
                status="in_progress",
                priority=1,
                issue_type="task",
                owner="agent_beta"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Assigned to agent gamma",
                description="",
                status="in_progress",
                priority=2,
                issue_type="task",
                owner="agent_gamma"
            )
        ]
        
        next_child = get_next_child_task("epic-1")
        
        # Should return None since all children are assigned to other agents
        assert next_child is None
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_all_children_complete_no_children(self, mock_get_children: Mock) -> None:
        """Test that no children means NOT complete (prevents premature closure)."""
        mock_get_children.return_value = []
        
        result = all_children_complete("epic-1")
        
        # No children should return False to prevent premature parent closure
        # This handles cases where children aren't registered yet or fetch failed
        assert result is False
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_all_children_complete_with_open_children(self, mock_get_children: Mock) -> None:
        """Test that open children means not all complete."""
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="done",
                priority=1,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task 2",
                description="",
                status="open",
                priority=2,
                issue_type="task"
            )
        ]
        
        result = all_children_complete("epic-1")
        
        assert result is False
    
    @patch('pokepoke.beads_hierarchy.get_children')
    def test_all_children_complete_all_done(self, mock_get_children: Mock) -> None:
        """Test that all done children returns True."""
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="done",
                priority=1,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task 2",
                description="",
                status="closed",
                priority=2,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-3",
                title="Task 3",
                description="",
                status="resolved",
                priority=3,
                issue_type="task"
            )
        ]
        
        result = all_children_complete("epic-1")
        
        assert result is True
    
    @patch('pokepoke.beads_hierarchy.subprocess.run')
    @patch('pokepoke.beads_hierarchy.all_children_complete')
    def test_close_parent_if_complete_not_complete(
        self, 
        mock_all_complete: Mock, 
        mock_run: Mock
    ) -> None:
        """Test that parent is not closed if children incomplete."""
        mock_all_complete.return_value = False
        
        result = close_parent_if_complete("epic-1")
        
        assert result is False
        mock_run.assert_not_called()
    
    @patch('pokepoke.beads_hierarchy.subprocess.run')
    @patch('pokepoke.beads_hierarchy.all_children_complete')
    def test_close_parent_if_complete_success(
        self, 
        mock_all_complete: Mock, 
        mock_run: Mock
    ) -> None:
        """Test that parent is closed when all children complete."""
        mock_all_complete.return_value = True
        mock_run.return_value = Mock(returncode=0)
        
        result = close_parent_if_complete("epic-1")
        
        assert result is True
        mock_run.assert_called_once_with(
            ['bd', 'close', 'epic-1', '-r', 'All child items completed'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
    
    @patch('pokepoke.beads_hierarchy.subprocess.run')
    def test_close_item_success(self, mock_run: Mock) -> None:
        """Test closing an item successfully."""
        mock_run.return_value = Mock(returncode=0)
        
        result = close_item("task-1", "Test completion")
        
        assert result is True
        mock_run.assert_called_once_with(
            ['bd', 'close', 'task-1', '--reason', 'Test completion'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
    
    @patch('pokepoke.beads_hierarchy.subprocess.run')
    def test_close_item_failure(self, mock_run: Mock) -> None:
        """Test handling close item failure."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'bd', stderr="Error closing item"
        )
        
        result = close_item("task-1", "Test completion")
        
        assert result is False
    
    @patch('pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_get_parent_id_no_dependencies(self, mock_get_issue: Mock) -> None:
        """Test getting parent ID when no dependencies exist."""
        mock_get_issue.return_value = IssueWithDependencies(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=None
        )
        
        parent_id = get_parent_id("task-1")
        
        assert parent_id is None
    
    @patch('pokepoke.beads_hierarchy.get_issue_dependencies')
    def test_get_parent_id_with_parent(self, mock_get_issue: Mock) -> None:
        """Test getting parent ID when parent dependency exists."""
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
        
        parent_id = get_parent_id("task-1")
        
        assert parent_id == "feature-1"
    
    @patch('pokepoke.beads_hierarchy.get_children')
    @patch('pokepoke.beads_hierarchy.close_parent_if_complete')
    def test_select_next_hierarchical_item_epic_with_children(
        self, 
        mock_close_parent: Mock,
        mock_get_children: Mock
    ) -> None:
        """Test hierarchical selection with epic that has children returns child task."""
        items = [
            BeadsWorkItem(
                id="epic-1",
                title="Epic",
                description="",
                status="open",
                priority=1,
                issue_type="epic"
            )
        ]
        # Mock: epic has an open child task (unassigned, so available)
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        
        selected = select_next_hierarchical_item(items)
        
        assert selected is not None
        assert selected.id == "task-1"
        mock_close_parent.assert_not_called()
    
    @patch('pokepoke.beads_hierarchy.get_children')
    @patch('pokepoke.beads_hierarchy.close_parent_if_complete')
    def test_select_next_hierarchical_item_epic_all_children_complete(
        self, 
        mock_close_parent: Mock,
        mock_get_children: Mock
    ) -> None:
        """Test hierarchical selection with epic where all children complete."""
        items = [
            BeadsWorkItem(
                id="epic-1",
                title="Epic",
                description="",
                status="open",
                priority=1,
                issue_type="epic"
            ),
            BeadsWorkItem(
                id="task-1",
                title="Standalone Task",
                description="",
                status="open",
                priority=2,
                issue_type="task"
            )
        ]
        # Mock: epic has children (but all complete - no available children)
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="child-1",
                title="Completed child",
                description="",
                status="done",
                priority=1,
                issue_type="task"
            )
        ]
        mock_close_parent.return_value = True
        
        selected = select_next_hierarchical_item(items)
        
        # Should auto-close epic and select the standalone task
        assert selected is not None
        assert selected.id == "task-1"
        mock_close_parent.assert_called_once_with("epic-1")
    
    @patch('pokepoke.beads_management.resolve_to_leaf_task')
    def test_select_next_hierarchical_item_standalone_task(
        self, 
        mock_resolve: Mock
    ) -> None:
        """Test hierarchical selection with standalone task."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        
        selected = select_next_hierarchical_item(items)
        
        assert selected is not None
        assert selected.id == "task-1"
        mock_resolve.assert_not_called()
    
    def test_select_next_hierarchical_item_empty_list(self) -> None:
        """Test hierarchical selection with empty list."""
        selected = select_next_hierarchical_item([])
        
        assert selected is None

    @patch('pokepoke.beads_hierarchy.get_children')
    def test_select_next_hierarchical_item_childless_feature(
        self,
        mock_get_children: Mock
    ) -> None:
        """Test hierarchical selection returns childless feature directly.
        
        When a feature has no children, it should be returned for direct work
        (the agent should break it down into tasks). Previously this was a bug
        where childless features were skipped, causing 'no work available'.
        """
        # Feature with no children
        feature = BeadsWorkItem(
            id="feature-1",
            title="Feature without children",
            description="",
            status="open",
            priority=1,
            issue_type="feature"
        )
        items = [feature]
        
        # Mock: feature has no children
        mock_get_children.return_value = []
        
        selected = select_next_hierarchical_item(items)
        
        # Should return the childless feature for direct work
        assert selected is not None
        assert selected.id == "feature-1"
        assert selected.issue_type == "feature"

    @patch('pokepoke.beads_hierarchy.get_children')
    def test_select_next_hierarchical_item_childless_epic(
        self,
        mock_get_children: Mock
    ) -> None:
        """Test hierarchical selection returns childless epic directly."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Epic without children",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        items = [epic]
        
        mock_get_children.return_value = []
        
        selected = select_next_hierarchical_item(items)
        
        assert selected is not None
        assert selected.id == "epic-1"
        assert selected.issue_type == "epic"

    @patch('pokepoke.beads_hierarchy.get_children')
    def test_select_next_hierarchical_item_prioritizes_tasks_over_childless_features(
        self,
        mock_get_children: Mock
    ) -> None:
        """Test that tasks are selected over childless features when same priority."""
        feature = BeadsWorkItem(
            id="feature-1",
            title="Childless feature",
            description="",
            status="open",
            priority=2,
            issue_type="feature"
        )
        task = BeadsWorkItem(
            id="task-1",
            title="Regular task",
            description="",
            status="open",
            priority=1,  # Higher priority (lower number)
            issue_type="task"
        )
        items = [feature, task]  # Feature listed first
        
        mock_get_children.return_value = []
        
        selected = select_next_hierarchical_item(items)
        
        # Task should be selected due to higher priority
        assert selected is not None
        assert selected.id == "task-1"


class TestResolveToLeafTask:
    """Tests for resolve_to_leaf_task recursive resolution."""

    def test_non_epic_feature_returned_directly(self) -> None:
        """Non-epic/feature items (tasks, bugs, chores) are returned directly."""
        task = BeadsWorkItem(
            id="task-1",
            title="Regular task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        result = resolve_to_leaf_task(task)
        
        assert result is not None
        assert result.id == "task-1"

    @patch('pokepoke.beads_hierarchy.get_children')
    def test_childless_epic_returned_directly(self, mock_get_children: Mock) -> None:
        """A childless epic should be returned for direct work (agent decomposes)."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Childless epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        mock_get_children.return_value = []
        
        result = resolve_to_leaf_task(epic)
        
        assert result is not None
        assert result.id == "epic-1"

    @patch('pokepoke.beads_hierarchy.get_children')
    def test_epic_with_child_task_returns_child(self, mock_get_children: Mock) -> None:
        """Epic with a child task should return the child task."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Child task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        
        result = resolve_to_leaf_task(epic)
        
        assert result is not None
        assert result.id == "task-1"

    @patch('pokepoke.beads_hierarchy.get_children')
    def test_epic_with_child_feature_resolves_recursively(
        self, mock_get_children: Mock
    ) -> None:
        """Epic -> feature -> task should resolve to the grandchild task.
        
        This is the core bug fix: we should never directly assign a feature
        that has children. Instead, we walk down to the leaf task.
        """
        epic = BeadsWorkItem(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        
        # First call: epic's children (a feature)
        # Second call: feature's children (a task)
        mock_get_children.side_effect = [
            [
                BeadsWorkItem(
                    id="feature-1",
                    title="Child feature",
                    description="",
                    status="open",
                    priority=1,
                    issue_type="feature"
                )
            ],
            [
                BeadsWorkItem(
                    id="task-1",
                    title="Grandchild task",
                    description="",
                    status="open",
                    priority=1,
                    issue_type="task"
                )
            ]
        ]
        
        result = resolve_to_leaf_task(epic)
        
        # Should resolve to the grandchild task, NOT the feature
        assert result is not None
        assert result.id == "task-1"
        assert result.issue_type == "task"

    @patch('pokepoke.beads_hierarchy.get_children')
    @patch('pokepoke.beads_hierarchy.close_parent_if_complete')
    def test_all_children_complete_auto_closes_parent(
        self,
        mock_close_parent: Mock,
        mock_get_children: Mock
    ) -> None:
        """When all children are complete, auto-close the parent and return None."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Done task",
                description="",
                status="done",
                priority=1,
                issue_type="task"
            )
        ]
        mock_close_parent.return_value = True
        
        result = resolve_to_leaf_task(epic)
        
        assert result is None
        mock_close_parent.assert_called_once_with("epic-1")

    @patch('pokepoke.beads_hierarchy.get_children')
    @patch('pokepoke.beads_hierarchy._is_assigned_to_current_user')
    def test_all_children_blocked_skips_parent(
        self,
        mock_is_current: Mock,
        mock_get_children: Mock
    ) -> None:
        """When all children are blocked (assigned to others), skip parent entirely."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-1",
                title="Assigned to other agent",
                description="",
                status="in_progress",
                priority=1,
                issue_type="task",
                owner="other_agent"
            )
        ]
        # Mock: item is assigned to someone else
        mock_is_current.return_value = False
        
        result = resolve_to_leaf_task(epic)
        
        assert result is None

    @patch('pokepoke.beads_hierarchy.get_children')
    @patch('pokepoke.beads_hierarchy.close_parent_if_complete')
    def test_child_feature_all_blocked_tries_next_sibling(
        self,
        mock_close_parent: Mock,
        mock_get_children: Mock
    ) -> None:
        """If a child feature's grandchildren are all blocked, try next sibling."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'
        
        # First call: epic's children (feature + task)
        # Second call: feature-1's children (all blocked)
        mock_get_children.side_effect = [
            [
                BeadsWorkItem(
                    id="feature-1",
                    title="Feature with blocked children",
                    description="",
                    status="open",
                    priority=1,
                    issue_type="feature"
                ),
                BeadsWorkItem(
                    id="task-2",
                    title="Available sibling task",
                    description="",
                    status="open",
                    priority=2,
                    issue_type="task"
                )
            ],
            [
                BeadsWorkItem(
                    id="task-blocked",
                    title="Blocked grandchild",
                    description="",
                    status="in_progress",
                    priority=1,
                    issue_type="task",
                    owner="other_agent"
                )
            ]
        ]
        mock_close_parent.return_value = False
        
        result = resolve_to_leaf_task(epic)
        
        # Should skip the blocked feature and return the sibling task
        assert result is not None
        assert result.id == "task-2"

    @patch('pokepoke.beads_hierarchy.get_children')
    def test_returns_highest_priority_child(self, mock_get_children: Mock) -> None:
        """Among available children, the highest priority one is returned."""
        feature = BeadsWorkItem(
            id="feature-1",
            title="Feature",
            description="",
            status="open",
            priority=1,
            issue_type="feature"
        )
        mock_get_children.return_value = [
            BeadsWorkItem(
                id="task-low",
                title="Low priority",
                description="",
                status="open",
                priority=3,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-high",
                title="High priority",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        
        result = resolve_to_leaf_task(feature)
        
        assert result is not None
        assert result.id == "task-high"

    def test_depth_limit_prevents_infinite_recursion(self) -> None:
        """Depth limit prevents infinite recursion."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Deep epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        
        # At max depth, should return None
        result = resolve_to_leaf_task(epic, _depth=10)
        
        assert result is None

    @patch('pokepoke.beads_hierarchy.get_children')
    @patch('pokepoke.beads_hierarchy.close_parent_if_complete')
    def test_epic_child_feature_all_grandchildren_complete_auto_closes(
        self,
        mock_close_parent: Mock,
        mock_get_children: Mock
    ) -> None:
        """When a child feature has all complete grandchildren, it auto-closes."""
        epic = BeadsWorkItem(
            id="epic-1",
            title="Epic",
            description="",
            status="open",
            priority=1,
            issue_type="epic"
        )
        
        # First call: epic's children (one feature)
        # Second call: feature's children (all done)
        mock_get_children.side_effect = [
            [
                BeadsWorkItem(
                    id="feature-1",
                    title="Feature",
                    description="",
                    status="open",
                    priority=1,
                    issue_type="feature"
                )
            ],
            [
                BeadsWorkItem(
                    id="task-done",
                    title="Done task",
                    description="",
                    status="done",
                    priority=1,
                    issue_type="task"
                )
            ]
        ]
        mock_close_parent.return_value = True
        
        result = resolve_to_leaf_task(epic)
        
        # Should return None after auto-closing both feature and epic
        assert result is None
        # close_parent_if_complete called for feature-1 first, then epic-1
        assert mock_close_parent.call_count == 2