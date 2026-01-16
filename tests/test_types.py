"""Unit tests for type definitions."""

import pytest
from src.pokepoke.types import BeadsWorkItem, CopilotResult, Dependency


class TestBeadsWorkItem:
    """Test BeadsWorkItem dataclass."""
    
    def test_create_basic_work_item(self) -> None:
        """Test creating a basic work item."""
        item = BeadsWorkItem(
            id="test-123",
            title="Test task",
            issue_type="task",
            status="open",
            priority=1,
            description=""
        )
        
        assert item.id == "test-123"
        assert item.title == "Test task"
        assert item.issue_type == "task"
        assert item.status == "open"
        assert item.priority == 1
    
    def test_create_work_item_with_description(self) -> None:
        """Test creating work item with description."""
        item = BeadsWorkItem(
            id="test-123",
            title="Test task",
            issue_type="task",
            status="open",
            priority=1,
            description="A detailed description"
        )
        
        assert item.description == "A detailed description"


class TestCopilotResult:
    """Test CopilotResult dataclass."""
    
    def test_create_successful_result(self) -> None:
        """Test creating a successful result."""
        result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Task completed"
        )
        
        assert result.work_item_id == "test-123"
        assert result.success is True
        assert result.output == "Task completed"
        assert result.error is None
    
    def test_create_failed_result(self) -> None:
        """Test creating a failed result."""
        result = CopilotResult(
            work_item_id="test-123",
            success=False,
            error="Something went wrong"
        )
        
        assert result.success is False
        assert result.error == "Something went wrong"


class TestDependency:
    """Test Dependency dataclass."""
    
    def test_create_dependency(self) -> None:
        """Test creating a dependency."""
        dep = Dependency(
            id="dep-456",
            title="Dependency task",
            issue_type="task",
            dependency_type="blocks"
        )
        
        assert dep.id == "dep-456"
        assert dep.dependency_type == "blocks"
