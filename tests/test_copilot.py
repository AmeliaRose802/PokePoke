"""Tests for copilot.py module (SDK-based implementation)."""

import pytest
from unittest.mock import patch, MagicMock

from pokepoke.copilot import (
    invoke_copilot
)
from pokepoke.types import BeadsWorkItem, CopilotResult


@pytest.fixture
def sample_work_item():
    """Create a sample work item for testing."""
    return BeadsWorkItem(
        id="test-123",
        title="Test work item",
        description="Test description",
        status="in_progress",
        priority=1,
        issue_type="task",
        labels=["testing", "coverage"]
    )


class TestInvokeCopilot:
    """Tests for invoke_copilot function (SDK-based)."""
    
    @patch('pokepoke.copilot.invoke_copilot_sdk_sync')
    def test_invoke_copilot_success(self, mock_sdk, sample_work_item):
        """Test successful invocation."""
        expected_result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Success",
            attempt_count=1
        )
        mock_sdk.return_value = expected_result
        
        result = invoke_copilot(sample_work_item)
        
        assert result == expected_result
        mock_sdk.assert_called_once()
    
    @patch('pokepoke.copilot.invoke_copilot_sdk_sync')
    def test_invoke_copilot_with_params(self, mock_sdk, sample_work_item):
        """Test invocation with custom parameters."""
        expected_result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Success",
            attempt_count=1
        )
        mock_sdk.return_value = expected_result
        
        result = invoke_copilot(
            sample_work_item,
            prompt="custom prompt",
            timeout=3600.0,
            deny_write=True
        )
        
        assert result == expected_result
        mock_sdk.assert_called_once_with(
            work_item=sample_work_item,
            prompt="custom prompt",
            retry_config=None,
            timeout=3600.0,
            deny_write=True,
            item_logger=None,
            model=None,
            cwd=None
        )

