"""Tests for invoke_copilot function (moved to ai_backends)."""

from unittest.mock import MagicMock, patch

from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.types_agent import CopilotResult


class TestInvokeCopilot:
    """Tests for invoke_copilot function (SDK-based)."""

    @patch('pokepoke.models.ai_backends.get_backend')
    def test_invoke_copilot_success(self, mock_backend_factory, sample_work_item):
        """Test successful invocation."""
        expected_result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Success",
            attempt_count=1
        )
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = expected_result
        mock_backend_factory.return_value = mock_backend

        result = invoke_copilot(sample_work_item)

        assert result == expected_result
        mock_backend_factory.assert_called_once_with(None)
        mock_backend.invoke.assert_called_once_with(
            work_item=sample_work_item,
            prompt=None,
            retry_config=None,
            timeout=None,
            deny_write=False,
            item_logger=None,
            model=None,
            cwd=None,
            template_name=None,
            session_id=None,
            is_resume=False,
            add_parent_dir=False
        )

    @patch('pokepoke.models.ai_backends.get_backend')
    def test_invoke_copilot_with_params(self, mock_backend_factory, sample_work_item):
        """Test invocation with custom parameters."""
        expected_result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Success",
            attempt_count=1
        )
        mock_backend = MagicMock()
        mock_backend.invoke.return_value = expected_result
        mock_backend_factory.return_value = mock_backend

        result = invoke_copilot(
            sample_work_item,
            prompt="custom prompt",
            timeout=3600.0,
            deny_write=True,
            provider="claude-code"
        )

        assert result == expected_result
        mock_backend_factory.assert_called_once_with("claude-code")
        mock_backend.invoke.assert_called_once_with(
            work_item=sample_work_item,
            prompt="custom prompt",
            retry_config=None,
            timeout=3600.0,
            deny_write=True,
            item_logger=None,
            model=None,
            cwd=None,
            template_name=None,
            session_id=None,
            is_resume=False,
            add_parent_dir=False
        )

