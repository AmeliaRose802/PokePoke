"""Tests for blocking dependency validation in work item selection."""

from unittest.mock import Mock, patch

from pokepoke.beads.beads_query import has_unmet_blocking_dependencies
from pokepoke.orchestration.work_item_selection import select_work_item
from pokepoke.types import BeadsWorkItem, Dependency, IssueWithDependencies


class TestBlockingDependencyValidation:
    """Test validation of blocking dependencies before claiming work items."""

    def test_has_unmet_blocking_dependencies_with_open_blocker(self) -> None:
        """Item with open blocking dependency should return True."""
        mock_issue = IssueWithDependencies(
            id="test-1",
            title="Test Issue",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="blocker-1",
                    title="Blocking Issue",
                    issue_type="task",
                    dependency_type="blocks",
                    status="open"
                )
            ]
        )

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', return_value=mock_issue):
            result = has_unmet_blocking_dependencies("test-1")
            assert result is True

    def test_has_unmet_blocking_dependencies_with_closed_blocker(self) -> None:
        """Item with closed blocking dependency should return False."""
        mock_issue = IssueWithDependencies(
            id="test-1",
            title="Test Issue",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="blocker-1",
                    title="Blocking Issue",
                    issue_type="task",
                    dependency_type="blocks",
                    status="closed"
                )
            ]
        )

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', return_value=mock_issue):
            result = has_unmet_blocking_dependencies("test-1")
            assert result is False

    def test_has_unmet_blocking_dependencies_with_non_blocking_dependency(self) -> None:
        """Item with open non-blocking dependency should return False."""
        mock_issue = IssueWithDependencies(
            id="test-1",
            title="Test Issue",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="related-1",
                    title="Related Issue",
                    issue_type="task",
                    dependency_type="related",
                    status="open"
                ),
                Dependency(
                    id="parent-1",
                    title="Parent Issue",
                    issue_type="epic",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', return_value=mock_issue):
            result = has_unmet_blocking_dependencies("test-1")
            assert result is False

    def test_has_unmet_blocking_dependencies_with_no_dependencies(self) -> None:
        """Item with no dependencies should return False."""
        mock_issue = IssueWithDependencies(
            id="test-1",
            title="Test Issue",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[]
        )

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', return_value=mock_issue):
            result = has_unmet_blocking_dependencies("test-1")
            assert result is False

    def test_has_unmet_blocking_dependencies_with_mixed_dependencies(self) -> None:
        """Item with closed blocker and open related should return False."""
        mock_issue = IssueWithDependencies(
            id="test-1",
            title="Test Issue",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="blocker-1",
                    title="Blocking Issue",
                    issue_type="task",
                    dependency_type="blocks",
                    status="closed"
                ),
                Dependency(
                    id="related-1",
                    title="Related Issue",
                    issue_type="task",
                    dependency_type="related",
                    status="open"
                )
            ]
        )

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', return_value=mock_issue):
            result = has_unmet_blocking_dependencies("test-1")
            assert result is False

    def test_has_unmet_blocking_dependencies_with_multiple_open_blockers(self) -> None:
        """Item with multiple open blocking dependencies should return True."""
        mock_issue = IssueWithDependencies(
            id="test-1",
            title="Test Issue",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="blocker-1",
                    title="First Blocker",
                    issue_type="task",
                    dependency_type="blocks",
                    status="open"
                ),
                Dependency(
                    id="blocker-2",
                    title="Second Blocker",
                    issue_type="task",
                    dependency_type="blocks",
                    status="closed"
                ),
                Dependency(
                    id="blocker-3",
                    title="Third Blocker",
                    issue_type="task",
                    dependency_type="blocks",
                    status="in_progress"
                )
            ]
        )

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', return_value=mock_issue):
            result = has_unmet_blocking_dependencies("test-1")
            assert result is True

    def test_has_unmet_blocking_dependencies_when_issue_not_found(self) -> None:
        """Should return False when issue details cannot be retrieved."""
        with patch('pokepoke.beads.beads_query.get_issue_dependencies', return_value=None):
            result = has_unmet_blocking_dependencies("nonexistent-1")
            assert result is False

    def test_child_of_blocked_parent_returns_true(self) -> None:
        """Child whose parent has an open blocker should return True."""
        child_issue = IssueWithDependencies(
            id="child-1",
            title="Child Task",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="parent-1",
                    title="Parent Feature",
                    issue_type="feature",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )
        parent_issue = IssueWithDependencies(
            id="parent-1",
            title="Parent Feature",
            status="open",
            priority=1,
            issue_type="feature",
            dependencies=[
                Dependency(
                    id="blocker-1",
                    title="Blocking Issue",
                    issue_type="task",
                    dependency_type="blocks",
                    status="open"
                )
            ]
        )

        def mock_get_deps(issue_id, **kwargs):
            return {"child-1": child_issue, "parent-1": parent_issue}.get(issue_id)

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', side_effect=mock_get_deps):
            result = has_unmet_blocking_dependencies("child-1")
            assert result is True

    def test_child_of_unblocked_parent_returns_false(self) -> None:
        """Child whose parent has no blockers should return False."""
        child_issue = IssueWithDependencies(
            id="child-1",
            title="Child Task",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="parent-1",
                    title="Parent Feature",
                    issue_type="feature",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )
        parent_issue = IssueWithDependencies(
            id="parent-1",
            title="Parent Feature",
            status="open",
            priority=1,
            issue_type="feature",
            dependencies=[]
        )

        def mock_get_deps(issue_id, **kwargs):
            return {"child-1": child_issue, "parent-1": parent_issue}.get(issue_id)

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', side_effect=mock_get_deps):
            result = has_unmet_blocking_dependencies("child-1")
            assert result is False

    def test_grandchild_of_blocked_grandparent_returns_true(self) -> None:
        """Grandchild should be blocked when grandparent has open blocker."""
        grandchild_issue = IssueWithDependencies(
            id="grandchild-1",
            title="Grandchild Task",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="parent-1",
                    title="Parent Feature",
                    issue_type="feature",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )
        parent_issue = IssueWithDependencies(
            id="parent-1",
            title="Parent Feature",
            status="open",
            priority=1,
            issue_type="feature",
            dependencies=[
                Dependency(
                    id="grandparent-1",
                    title="Grandparent Epic",
                    issue_type="epic",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )
        grandparent_issue = IssueWithDependencies(
            id="grandparent-1",
            title="Grandparent Epic",
            status="open",
            priority=1,
            issue_type="epic",
            dependencies=[
                Dependency(
                    id="blocker-1",
                    title="Blocking Issue",
                    issue_type="task",
                    dependency_type="blocks",
                    status="in_progress"
                )
            ]
        )

        def mock_get_deps(issue_id, **kwargs):
            return {
                "grandchild-1": grandchild_issue,
                "parent-1": parent_issue,
                "grandparent-1": grandparent_issue,
            }.get(issue_id)

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', side_effect=mock_get_deps):
            result = has_unmet_blocking_dependencies("grandchild-1")
            assert result is True

    def test_cycle_in_parent_chain_does_not_infinite_loop(self) -> None:
        """Circular parent references should not cause infinite recursion."""
        issue_a = IssueWithDependencies(
            id="a",
            title="Issue A",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="b",
                    title="Issue B",
                    issue_type="task",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )
        issue_b = IssueWithDependencies(
            id="b",
            title="Issue B",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="a",
                    title="Issue A",
                    issue_type="task",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )

        def mock_get_deps(issue_id, **kwargs):
            return {"a": issue_a, "b": issue_b}.get(issue_id)

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', side_effect=mock_get_deps):
            result = has_unmet_blocking_dependencies("a")
            assert result is False

    def test_child_of_parent_with_closed_blocker_returns_false(self) -> None:
        """Child should not be blocked when parent's blocker is closed."""
        child_issue = IssueWithDependencies(
            id="child-1",
            title="Child Task",
            status="open",
            priority=1,
            issue_type="task",
            dependencies=[
                Dependency(
                    id="parent-1",
                    title="Parent Feature",
                    issue_type="feature",
                    dependency_type="parent",
                    status="open"
                )
            ]
        )
        parent_issue = IssueWithDependencies(
            id="parent-1",
            title="Parent Feature",
            status="open",
            priority=1,
            issue_type="feature",
            dependencies=[
                Dependency(
                    id="blocker-1",
                    title="Blocking Issue",
                    issue_type="task",
                    dependency_type="blocks",
                    status="closed"
                )
            ]
        )

        def mock_get_deps(issue_id, **kwargs):
            return {"child-1": child_issue, "parent-1": parent_issue}.get(issue_id)

        with patch('pokepoke.beads.beads_query.get_issue_dependencies', side_effect=mock_get_deps):
            result = has_unmet_blocking_dependencies("child-1")
            assert result is False

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_select_work_item_passes_all_items_to_hierarchical_selection(
        self,
        mock_select_hierarchical: Mock,
    ) -> None:
        """select_work_item no longer filters by blocking dependencies per-item.

        Blocking dependency filtering was removed from select_work_item for
        performance (bd ready already filters blocked items). All items from
        the ready queue are passed directly to hierarchical selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task One",
                status="open",
                priority=1,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task Two",
                status="open",
                priority=2,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-3",
                title="Task Three",
                status="open",
                priority=3,
                issue_type="task"
            )
        ]

        mock_select_hierarchical.return_value = items[1]

        select_work_item(items, interactive=False)

        # All items should be passed through to hierarchical selection
        # (blocking dep filtering is handled upstream by bd ready)
        mock_select_hierarchical.assert_called_once()
        call_args = mock_select_hierarchical.call_args[0][0]
        assert len(call_args) == 3

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_select_work_item_with_single_item_passes_to_hierarchical(
        self,
        mock_select_hierarchical: Mock,
    ) -> None:
        """Single item should be passed to hierarchical selection regardless.

        Blocking dependency filtering removed from select_work_item for
        performance. bd ready upstream handles blocker-aware filtering."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task One",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]

        mock_select_hierarchical.return_value = items[0]

        result = select_work_item(items, interactive=False)

        assert result is not None
        mock_select_hierarchical.assert_called_once()
