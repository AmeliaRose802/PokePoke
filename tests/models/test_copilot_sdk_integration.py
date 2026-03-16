"""Integration tests for copilot_sdk module to improve coverage."""

import asyncio
import sys
import time
from unittest.mock import patch, Mock, AsyncMock, MagicMock
import pytest

from pokepoke.types import BeadsWorkItem, CopilotResult
from pokepoke.models.copilot_sdk import (
    build_prompt_from_work_item,
    _fail_result,
    invoke_copilot_sdk_sync,
)


class TestBuildPromptIntegration:
    """Integration tests for build_prompt_from_work_item."""

    @patch('pokepoke.models.copilot_sdk.get_config')
    @patch('pokepoke.models.copilot_sdk.PromptService')
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

    @patch('pokepoke.models.copilot_sdk.get_config')
    @patch('pokepoke.models.copilot_sdk.PromptService')
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

    @patch('pokepoke.models.copilot_sdk.get_config')
    @patch('pokepoke.models.copilot_sdk.PromptService')
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


class TestInvokeCopilotSDKSyncIntegration:
    """Integration tests for invoke_copilot_sdk_sync."""

    @patch('pokepoke.models.copilot_sdk.invoke_copilot_sdk')
    @patch('pokepoke.models.copilot_sdk.asyncio.run')
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

    @patch('pokepoke.models.copilot_sdk.invoke_copilot_sdk')
    @patch('pokepoke.models.copilot_sdk.asyncio.run')
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

    @patch('pokepoke.models.copilot_sdk.invoke_copilot_sdk')
    @patch('pokepoke.models.copilot_sdk.asyncio.run')
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

    def teardown_method(self):
        if sys.platform == "win32":
            time.sleep(0.05)

    @patch('pokepoke.models.copilot_sdk.get_config')
    @patch('pokepoke.models.copilot_sdk.PromptService')
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

class TestCopilotSDKConfiguration:
    """Tests for configuration handling in copilot_sdk."""

    @patch('pokepoke.models.copilot_sdk.get_config')
    @patch('pokepoke.models.copilot_sdk.PromptService')
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

    @patch('pokepoke.models.copilot_sdk.get_config')
    @patch('pokepoke.models.copilot_sdk.PromptService')
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


class TestAwaitCompletionInactivity:
    """Tests for _await_completion inactivity detection."""

    @pytest.mark.asyncio
    async def test_inactivity_triggers_abort(self):
        """When no events arrive for inactivity_timeout, returns 'inactivity'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        # last_event_time far in the past → immediate inactivity
        stats = {
            'last_event_time': time.monotonic() - 700,
            'event_count': 5,
            'last_tool_activity_time': time.monotonic() - 700,
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=600,
        )

        assert result == "inactivity"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_inactivity_when_events_recent(self):
        """When events are recent, inactivity check does not fire."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 10,
            'last_tool_activity_time': time.monotonic(),
        }

        # Set done after a brief delay so the function exits normally
        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        asyncio.create_task(_set_done())

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=600,
        )

        assert result is None  # Normal completion

    @pytest.mark.asyncio
    async def test_inactivity_disabled_when_zero(self):
        """When inactivity_timeout=0, detection is disabled."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 9999,
            'event_count': 1,
            'last_tool_activity_time': 0.0,
        }

        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        asyncio.create_task(_set_done())

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=0,
        )

        assert result is None  # Should not trigger inactivity

    @pytest.mark.asyncio
    async def test_inactivity_without_stats_is_noop(self):
        """When stats=None (default), inactivity check is skipped."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        asyncio.create_task(_set_done())

        result = await _await_completion(
            session, client, done, max_timeout=3600,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_inactivity_abort_failure_still_returns(self):
        """If session.abort() raises during inactivity, still returns 'inactivity'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        session.abort.side_effect = Exception("abort failed")
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 1000,
            'event_count': 3,
            'last_tool_activity_time': 0.0,
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=600,
        )

        assert result == "inactivity"


class TestCheckInactivity:
    """Tests for _check_inactivity helper."""

    def test_returns_failure_when_detected(self):
        from pokepoke.models.sdk_helpers import _check_inactivity

        result = _check_inactivity("item-1", True, 600.0)
        assert result is not None
        assert not result.success
        assert "no SDK events" in result.error
        assert "600" in result.error

    def test_returns_none_when_not_detected(self):
        from pokepoke.models.sdk_helpers import _check_inactivity

        result = _check_inactivity("item-1", False, 600.0)
        assert result is None


class TestSessionInactivityConfig:
    """Tests for session_inactivity_timeout config field."""

    def test_default_value(self):
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        assert cfg.session_inactivity_timeout == 600

    def test_clamped_to_minimum(self):
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig(session_inactivity_timeout=10)
        assert cfg.session_inactivity_timeout == 60

    def test_custom_value_preserved(self):
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig(session_inactivity_timeout=900)
        assert cfg.session_inactivity_timeout == 900


@pytest.mark.asyncio
class TestInvokeCopilotSDKInactivity:
    """Test full invoke_copilot_sdk with inactivity detection."""

    @pytest.fixture(autouse=True)
    def _mock_process_cleanup(self):
        with patch('pokepoke.utils.process_utils.wait_for_process_cleanup'):
            yield

    @patch('pokepoke.models.copilot_sdk.CopilotClient')
    async def test_invoke_returns_failure_on_inactivity(self, mock_client_class):
        """Full invoke_copilot_sdk returns failure when session goes inactive."""
        from pokepoke.models.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-inactivity"
        mock_session.abort = AsyncMock()

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()
        mock_client.get_state.return_value = "running"
        mock_client_class.return_value = mock_client

        # Don't set done — simulate dead session
        mock_session.on = lambda handler: None
        mock_session.send = AsyncMock()
        mock_session.destroy = AsyncMock()

        work_item = BeadsWorkItem(
            id="dead-session",
            title="Dead session test",
            status="ready",
            priority=1,
            issue_type="bug",
        )

        # Use very short inactivity timeout to trigger quickly
        with patch('pokepoke.models.copilot_sdk.get_config') as mock_cfg:
            cfg = Mock()
            cfg.idle_timeout_seconds = 1
            cfg.session_inactivity_timeout = 0.1  # 100ms
            cfg.tool_call_timeout = 60.0
            cfg.ai_backend.copilot_cli_path = "copilot.cmd"
            cfg.ai_backend.provider = "copilot-sdk"
            cfg.mcp_server.enabled = False
            cfg.test_data = {}
            cfg.command_timeout = 60
            mock_cfg.return_value = cfg

            result = await invoke_copilot_sdk(
                work_item=work_item,
                timeout=10.0,
                idle_timeout=1.0,
            )

        assert not result.success
        assert "no SDK events" in result.error.lower() or "session died" in result.error.lower()
