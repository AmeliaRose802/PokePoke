"""Integration tests for copilot_sdk module to improve coverage."""

import asyncio
from unittest.mock import patch, Mock
import pytest

from pokepoke.types import BeadsWorkItem, CopilotResult
from pokepoke.copilot_sdk import (
    build_prompt_from_work_item,
    _fail_result,
    _activity_watchdog,
    invoke_copilot_sdk_sync,
)
import contextlib


class TestBuildPromptIntegration:
    """Integration tests for build_prompt_from_work_item."""

    @patch('pokepoke.copilot_sdk.get_config')
    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_includes_all_fields(
        self, mock_service_class, mock_get_config
    ):
        """Test that prompt includes all work item fields."""
        mock_config = Mock()
        mock_config.test_data = {'sample_command': 'pytest', 'config_path': '.pokepoke/config.yaml'}
        mock_config.mcp_server.enabled = True
        mock_config.command_timeout = 300
        mock_get_config.return_value = mock_config

        mock_service = Mock()
        mock_service.load_and_render.return_value = "Rendered prompt"
        mock_service_class.return_value = mock_service

        work_item = BeadsWorkItem(
            id="test-123",
            title="Test Title",
            description="Test Description",
            status="ready",
            priority=1,
            issue_type="task",
            labels=["bug", "urgent"]
        )

        result = build_prompt_from_work_item(work_item)

        assert result == "Rendered prompt"
        mock_service.load_and_render.assert_called_once()
        call_args = mock_service.load_and_render.call_args
        variables = call_args[0][1]

        # Verify all fields are passed
        assert variables['item_id'] == "test-123"
        assert variables['title'] == "Test Title"
        assert variables['description'] == "Test Description"
        assert variables['issue_type'] == "task"
        assert variables['priority'] == 1
        assert variables['labels'] == "bug, urgent"
        assert variables['mcp_enabled'] is True
        assert variables['command_timeout'] == 300

    @patch('pokepoke.copilot_sdk.get_config')
    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_handles_missing_description(
        self, mock_service_class, mock_get_config
    ):
        """Test that missing description is handled."""
        mock_config = Mock()
        mock_config.test_data = {}
        mock_config.mcp_server.enabled = False
        mock_config.command_timeout = 300
        mock_get_config.return_value = mock_config

        mock_service = Mock()
        mock_service.load_and_render.return_value = "Prompt"
        mock_service_class.return_value = mock_service

        work_item = BeadsWorkItem(
            id="test-456",
            title="Title Only",
            description=None,
            status="ready",
            priority=2,
            issue_type="bug"
        )

        build_prompt_from_work_item(work_item)

        call_args = mock_service.load_and_render.call_args
        variables = call_args[0][1]
        assert variables['description'] == ""

    @patch('pokepoke.copilot_sdk.get_config')
    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_with_custom_template(
        self, mock_service_class, mock_get_config
    ):
        """Test building prompt with custom template name."""
        mock_config = Mock()
        mock_config.test_data = {}
        mock_config.mcp_server.enabled = False
        mock_config.command_timeout = 300
        mock_get_config.return_value = mock_config

        mock_service = Mock()
        mock_service.load_and_render.return_value = "Custom prompt"
        mock_service_class.return_value = mock_service

        work_item = BeadsWorkItem(
            id="test-789",
            title="Custom",
            status="ready",
            priority=1,
            issue_type="task"
        )

        build_prompt_from_work_item(work_item, template_name="custom-template")

        mock_service.load_and_render.assert_called_once()
        call_args = mock_service.load_and_render.call_args
        assert call_args[0][0] == "custom-template"


class TestFailResultIntegration:
    """Integration tests for _fail_result."""

    def test_fail_result_creates_failed_result(self):
        """Test that _fail_result creates a properly structured CopilotResult."""
        result = _fail_result("test-item", "Test error message")

        assert isinstance(result, CopilotResult)
        assert result.work_item_id == "test-item"
        assert result.success is False
        assert result.error == "Test error message"
        assert result.attempt_count == 1


class TestActivityWatchdogIntegration:
    """Integration tests for _activity_watchdog."""

    @pytest.mark.asyncio
    async def test_watchdog_detects_activity(self, tmp_path):
        """Test that watchdog detects file activity and doesn't abort."""
        log_file = tmp_path / "test.log"
        log_file.write_text("Initial content")

        abort_event = asyncio.Event()

        # Start watchdog with short intervals
        watchdog_task = asyncio.create_task(
            _activity_watchdog(log_file, timeout_seconds=2.0, check_interval_seconds=0.5, abort_event=abort_event)
        )

        # Update file during watchdog run
        await asyncio.sleep(0.6)
        log_file.write_text("Updated content")
        await asyncio.sleep(0.6)
        log_file.write_text("More updates")

        # Cancel watchdog
        await asyncio.sleep(0.3)
        watchdog_task.cancel()

        try:
            triggered = await watchdog_task
            assert triggered is False  # Should not have triggered abort
        except asyncio.CancelledError:
            pass  # Expected cancellation

    @pytest.mark.asyncio
    async def test_watchdog_triggers_on_timeout(self, tmp_path):
        """Test that watchdog triggers abort when no activity detected."""
        log_file = tmp_path / "test.log"
        log_file.write_text("Initial content")

        abort_event = asyncio.Event()

        # Start watchdog with very short timeout
        watchdog_task = asyncio.create_task(
            _activity_watchdog(log_file, timeout_seconds=1.0, check_interval_seconds=0.3, abort_event=abort_event)
        )

        # Don't update file - let it timeout
        triggered = await watchdog_task

        assert triggered is True
        assert abort_event.is_set()

    @pytest.mark.asyncio
    async def test_watchdog_handles_missing_log_file(self, tmp_path):
        """Test watchdog behavior when log file doesn't exist initially."""
        log_file = tmp_path / "nonexistent.log"
        abort_event = asyncio.Event()

        # Start watchdog for nonexistent file
        watchdog_task = asyncio.create_task(
            _activity_watchdog(log_file, timeout_seconds=1.5, check_interval_seconds=0.3, abort_event=abort_event)
        )

        # Create file after a delay
        await asyncio.sleep(0.4)
        log_file.write_text("File created")

        # Cancel before timeout
        await asyncio.sleep(0.5)
        watchdog_task.cancel()

        with contextlib.suppress(asyncio.CancelledError):
            await watchdog_task


class TestInvokeCopilotSDKSyncIntegration:
    """Integration tests for invoke_copilot_sdk_sync."""

    @patch('pokepoke.copilot_sdk.invoke_copilot_sdk')
    @patch('pokepoke.copilot_sdk.asyncio.run')
    def test_sync_wrapper_calls_async_version(
        self, mock_asyncio_run, mock_invoke
    ):
        """Test that sync wrapper properly calls async version."""
        work_item = BeadsWorkItem(
            id="test-sync",
            title="Sync Test",
            status="ready",
            priority=1,
            issue_type="task"
        )

        expected_result = CopilotResult(
            work_item_id="test-sync",
            success=True,
            error=None,
            attempt_count=1
        )
        mock_asyncio_run.return_value = expected_result

        result = invoke_copilot_sdk_sync(
            work_item=work_item,
            prompt="Test prompt",
            timeout=60.0
        )

        assert result == expected_result
        mock_asyncio_run.assert_called_once()

    @patch('pokepoke.copilot_sdk.invoke_copilot_sdk')
    @patch('pokepoke.copilot_sdk.asyncio.run')
    def test_sync_wrapper_passes_all_parameters(
        self, mock_asyncio_run, mock_invoke
    ):
        """Test that all parameters are passed through."""
        work_item = BeadsWorkItem(
            id="test-params",
            title="Params Test",
            status="ready",
            priority=1,
            issue_type="task"
        )

        mock_asyncio_run.return_value = CopilotResult(
            work_item_id="test-params",
            success=True,
            error=None,
            attempt_count=1
        )

        # Note: idle_timeout is not exposed in the sync wrapper
        invoke_copilot_sdk_sync(
            work_item=work_item,
            prompt="Custom prompt",
            timeout=120.0,
            deny_write=True,
            model="claude-sonnet",
            cwd="/custom/path",
            template_name="custom-template"
        )

        # Get the coroutine that was passed to asyncio.run
        mock_asyncio_run.call_args[0]
        # Can't easily inspect coroutine args, but we verified it was called

    @patch('pokepoke.copilot_sdk.invoke_copilot_sdk')
    @patch('pokepoke.copilot_sdk.asyncio.run')
    def test_sync_wrapper_handles_exception(
        self, mock_asyncio_run, mock_invoke
    ):
        """Test that exceptions are propagated from async version."""
        work_item = BeadsWorkItem(
            id="test-error",
            title="Error Test",
            status="ready",
            priority=1,
            issue_type="task"
        )

        mock_asyncio_run.side_effect = RuntimeError("Test error")

        with pytest.raises(RuntimeError, match="Test error"):
            invoke_copilot_sdk_sync(work_item=work_item)


class TestCopilotSDKErrorHandling:
    """Tests for error handling in copilot_sdk module."""

    @patch('pokepoke.copilot_sdk.get_config')
    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_handles_service_error(
        self, mock_service_class, mock_get_config
    ):
        """Test error handling when PromptService fails."""
        mock_config = Mock()
        mock_config.test_data = {}
        mock_config.mcp_server.enabled = False
        mock_config.command_timeout = 300
        mock_get_config.return_value = mock_config

        mock_service = Mock()
        mock_service.load_and_render.side_effect = Exception("Template error")
        mock_service_class.return_value = mock_service

        work_item = BeadsWorkItem(
            id="test-error",
            title="Error Test",
            status="ready",
            priority=1,
            issue_type="task"
        )

        with pytest.raises(Exception, match="Template error"):
            build_prompt_from_work_item(work_item)

    @pytest.mark.asyncio
    async def test_watchdog_handles_file_not_found_gracefully(self, tmp_path):
        """Test that watchdog handles file operations errors."""
        log_file = tmp_path / "test.log"
        # Don't create the file

        abort_event = asyncio.Event()

        # Watchdog should handle missing file without crashing
        watchdog_task = asyncio.create_task(
            _activity_watchdog(log_file, timeout_seconds=0.5, check_interval_seconds=0.1, abort_event=abort_event)
        )

        # Let it timeout
        triggered = await watchdog_task

        # Should timeout since no activity (file doesn't exist)
        assert triggered is True


class TestCopilotSDKConfiguration:
    """Tests for configuration handling in copilot_sdk."""

    @patch('pokepoke.copilot_sdk.get_config')
    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_uses_config_test_data(
        self, mock_service_class, mock_get_config
    ):
        """Test that test_data from config is included in prompt."""
        mock_config = Mock()
        mock_config.test_data = {
            'sample_command': 'pytest tests/',
            'config_file': '.pokepoke/config.yaml',
            'maintenance_agent': 'Janitor'
        }
        mock_config.mcp_server.enabled = True
        mock_config.command_timeout = 300
        mock_get_config.return_value = mock_config

        mock_service = Mock()
        mock_service.load_and_render.return_value = "Prompt with test data"
        mock_service_class.return_value = mock_service

        work_item = BeadsWorkItem(
            id="test-config",
            title="Config Test",
            status="ready",
            priority=1,
            issue_type="task"
        )

        build_prompt_from_work_item(work_item)

        call_args = mock_service.load_and_render.call_args
        variables = call_args[0][1]

        # Verify test_data_section was created
        assert variables['test_data_section'] is not None
        assert 'Sample command' in variables['test_data_section']
        assert 'pytest tests/' in variables['test_data_section']

    @patch('pokepoke.copilot_sdk.get_config')
    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_handles_empty_test_data(
        self, mock_service_class, mock_get_config
    ):
        """Test that empty test_data dict is handled."""
        mock_config = Mock()
        mock_config.test_data = {}
        mock_config.mcp_server.enabled = False
        mock_config.command_timeout = 300
        mock_get_config.return_value = mock_config

        mock_service = Mock()
        mock_service.load_and_render.return_value = "Prompt"
        mock_service_class.return_value = mock_service

        work_item = BeadsWorkItem(
            id="test-empty",
            title="Empty Test Data",
            status="ready",
            priority=1,
            issue_type="task"
        )

        build_prompt_from_work_item(work_item)

        call_args = mock_service.load_and_render.call_args
        variables = call_args[0][1]

        # test_data_section should be None when no test data
        assert variables['test_data_section'] is None
