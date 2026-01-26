"""Unit tests for hierarchical work assignment."""

import subprocess
from unittest.mock import Mock, patch, call
import json
import pytest

from src.pokepoke.beads import (
    get_children,
    get_next_child_task,
    all_children_complete,
    close_parent_if_complete,
    select_next_hierarchical_item,
    get_parent_id,
    close_item
)
from src.pokepoke.types import BeadsWorkItem, IssueWithDependencies, Dependency


class TestHierarchicalWorkAssignment:
    """Test hierarchical work assignment functions."""
    
    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
    def test_get_next_child_task_no_children(self, mock_get_children: Mock) -> None:
        """Test getting next child when there are no children."""
        mock_get_children.return_value = []
        
        next_child = get_next_child_task("epic-1")
        
        assert next_child is None
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
    def test_all_children_complete_no_children(self, mock_get_children: Mock) -> None:
        """Test that no children means all complete (trivially true)."""
        mock_get_children.return_value = []
        
        result = all_children_complete("epic-1")
        
        assert result is True
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_children')
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
    
    @patch('src.pokepoke.beads_hierarchy.subprocess.run')
    @patch('src.pokepoke.beads_hierarchy.all_children_complete')
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
    
    @patch('src.pokepoke.beads_hierarchy.subprocess.run')
    @patch('src.pokepoke.beads_hierarchy.all_children_complete')
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
    
    @patch('src.pokepoke.beads_hierarchy.subprocess.run')
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
    
    @patch('src.pokepoke.beads_hierarchy.subprocess.run')
    def test_close_item_failure(self, mock_run: Mock) -> None:
        """Test handling close item failure."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 'bd', stderr="Error closing item"
        )
        
        result = close_item("task-1", "Test completion")
        
        assert result is False
    
    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
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
    
    @patch('src.pokepoke.beads_hierarchy.get_issue_dependencies')
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
    
    @patch('src.pokepoke.beads_management.get_next_child_task')
    @patch('src.pokepoke.beads_management.close_parent_if_complete')
    def test_select_next_hierarchical_item_epic_with_children(
        self, 
        mock_close_parent: Mock,
        mock_get_next_child: Mock
    ) -> None:
        """Test hierarchical selection with epic that has children."""
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
        mock_get_next_child.return_value = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        selected = select_next_hierarchical_item(items)
        
        assert selected is not None
        assert selected.id == "task-1"
        mock_close_parent.assert_not_called()
    
    @patch('src.pokepoke.beads_management.get_next_child_task')
    @patch('src.pokepoke.beads_management.close_parent_if_complete')
    def test_select_next_hierarchical_item_epic_all_children_complete(
        self, 
        mock_close_parent: Mock,
        mock_get_next_child: Mock
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
        mock_get_next_child.return_value = None  # All children complete
        mock_close_parent.return_value = True
        
        selected = select_next_hierarchical_item(items)
        
        # Should close epic and select the standalone task
        assert selected is not None
        assert selected.id == "task-1"
        mock_close_parent.assert_called_once_with("epic-1")
    
    @patch('src.pokepoke.beads_management.get_next_child_task')
    def test_select_next_hierarchical_item_standalone_task(
        self, 
        mock_get_next_child: Mock
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
        mock_get_next_child.assert_not_called()
    
    def test_select_next_hierarchical_item_empty_list(self) -> None:
        """Test hierarchical selection with empty list."""
        selected = select_next_hierarchical_item([])
        
        assert selected is None
