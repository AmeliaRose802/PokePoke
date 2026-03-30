"""Integration tests for copilot_sdk module to improve coverage."""

import asyncio
import sys
import time
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from pokepoke.models.copilot_sdk import (
    _fail_result,
    build_prompt_from_work_item,
    invoke_copilot_sdk_sync,
)
from pokepoke.types import BeadsWorkItem, CopilotResult


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
    async def test_inactivity_suppressed_during_tool_cooldown_grace(self):
        """When a tool just finished, grace period prevents inactivity kill."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        # last_event_time far in the past but tool activity very recent
        stats = {
            'last_event_time': time.monotonic() - 700,
            'event_count': 5,
            'last_tool_activity_time': time.monotonic() - 10,  # 10s ago — within 60s grace
        }

        # Set done after a brief delay so the function exits normally
        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=600,
        )

        assert result is None  # Normal completion, NOT inactivity
        session.abort.assert_not_called()

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
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

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
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

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
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

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
    """Tests for inactivity detection via _check_abort_result helper."""

    def test_returns_failure_when_detected(self):
        from pokepoke.models.sdk_helpers import _check_abort_result

        result = _check_abort_result("item-1", True, 600.0, False, 600.0)
        assert result is not None
        assert not result.success
        assert "no SDK events" in result.error
        assert "600" in result.error

    def test_returns_none_when_not_detected(self):
        from pokepoke.models.sdk_helpers import _check_abort_result

        result = _check_abort_result("item-1", False, 600.0, False, 600.0)
        assert result is None


class TestSessionInactivityConfig:
    """Tests for session_inactivity_timeout config field."""

    def test_default_value(self):
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        assert cfg.session_inactivity_timeout == 900

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
            cfg.process_output_timeout = 9999  # Don't trigger process output timeout
            cfg.max_ping_failures = 999  # Don't trigger ping liveness
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


# ── Process-level liveness checks ────────────────────────────────────────────


class TestAwaitCompletionPingLiveness:
    """Tests for _await_completion consecutive ping failure detection."""

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_consecutive_ping_failures_trigger_process_dead(self):
        """When ping fails max_ping_failures times in a row, returns 'process_dead'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        # Ping always fails
        client.ping = AsyncMock(side_effect=Exception("connection refused"))
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        # Shift last_event_time back to ensure heartbeat fires immediately
        stats['last_event_time'] = time.monotonic() - 100

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,  # Don't trigger inactivity
            max_ping_failures=1,  # Fail after 1 ping failure for fast test
        )

        assert result == "process_dead"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_ping_success_resets_failure_count(self):
        """A successful ping resets the consecutive failure counter."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        # Ping succeeds
        client.ping = AsyncMock()
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        # Set done quickly so we exit normally
        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=3,
        )

        assert result is None  # Normal completion
        session.abort.assert_not_called()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_process_dead_abort_failure_still_returns(self):
        """If session.abort() raises during process death, still returns 'process_dead'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        session.abort.side_effect = Exception("abort failed")
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=Exception("connection refused"))
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 100,
            'event_count': 3,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=1,
        )

        assert result == "process_dead"

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_ping_fails_with_pending_tools_but_process_exited_zero_is_process_dead(self):
        """When pings fail, work done, pending_tool_calls>0, process exited 0 — stale pending tools means process_dead."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        # Simulate a process that exited cleanly
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.poll.return_value = 0
        client._process = mock_process

        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 100,
            'event_count': 50,
            'last_tool_activity_time': time.monotonic() - 10,
            'pending_tool_calls': 1,  # Stale pending tool call
            'tool_start_times': {},
            'turn_count': 3,  # Work was done
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=1,
        )

        # With AND logic, all three conditions (work done, no pending, clean exit)
        # must hold. Stale pending tools indicate abnormal state → process_dead.
        assert result == "process_dead"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_ping_fails_with_pending_tools_and_process_exited_nonzero_is_process_dead(self):
        """When pings fail, work was done, pending_tool_calls>0 and process exited non-zero, declare dead."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        # Simulate a process that crashed
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.poll.return_value = 1
        client._process = mock_process

        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 100,
            'event_count': 50,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 1,
            'tool_start_times': {},
            'turn_count': 3,
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=1,
        )

        assert result == "process_dead"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_ping_fails_with_pending_tools_and_live_process_not_counted(self):
        """Ping failures while tools are actively running should not count toward kill threshold."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=Exception("connection refused"))
        # Process is still alive (returncode is None)
        mock_process = MagicMock()
        mock_process.returncode = None
        client._process = mock_process

        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 10,
            'event_count': 50,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 1,  # Tool is actively running
            'tool_start_times': {'tool-1': time.monotonic()},
            'turn_count': 3,
        }

        # Let 3 heartbeat cycles pass, then complete normally
        async def _set_done():
            await asyncio.sleep(0.5)
            done.set()
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            tool_call_timeout=9999,
            max_ping_failures=1,  # Would kill after 1 failure if counted
        )

        # Should complete normally — ping failures during tool calls don't count
        assert result is None
        session.abort.assert_not_called()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_ping_fails_work_done_no_pending_no_process_attr_is_process_dead(self):
        """When pings fail, work done, no pending, no _process attr — cannot verify clean exit, so process_dead."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock(spec=[])  # No _process attribute
        client.get_state = MagicMock(return_value="running")
        client.ping = AsyncMock(side_effect=Exception("connection refused"))

        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 100,
            'event_count': 50,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 0,
            'tool_start_times': {},
            'turn_count': 5,
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=1,
        )

        assert result == "process_dead"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_crashed_process_no_pending_not_treated_as_completion(self):
        """When process crashed (exit 1), work done, no pending — must NOT treat as completion."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        # Simulate a crashed process
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.poll.return_value = 1
        client._process = mock_process

        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 100,
            'event_count': 50,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 0,  # No pending — this was the bug trigger
            'tool_start_times': {},
            'turn_count': 3,  # Work was done
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=1,
        )

        assert result == "process_dead"
        session.abort.assert_called_once()


class TestAwaitCompletionProcessOutputTimeout:
    """Tests for _await_completion process output timeout."""

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_output_timeout_with_ping_failure_triggers_process_dead(self):
        """No events for process_output_timeout AND ping fails -> process_dead."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=Exception("connection refused"))
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 400,  # 400s ago
            'event_count': 5,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,  # Don't trigger inactivity
            process_output_timeout=300,  # Should trigger
            max_ping_failures=999,  # Don't trigger consecutive ping
        )

        assert result == "process_dead"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_output_timeout_suppressed_when_ping_succeeds(self):
        """Even if no events for process_output_timeout, ping success means alive."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock()  # Ping succeeds
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 400,  # 400s ago, but ping OK
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            process_output_timeout=300,
            max_ping_failures=999,
        )

        assert result is None  # Normal completion, NOT process_dead

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_output_timeout_suppressed_with_pending_tools(self):
        """When tools are pending, process output timeout does not fire."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=Exception("connection refused"))
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 400,
            'event_count': 5,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 2,  # Tools are running
            'tool_start_times': {},
        }

        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            process_output_timeout=300,
            max_ping_failures=999,
        )

        assert result is None  # Should not fire with pending tools

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_output_timeout_disabled_when_zero(self):
        """When process_output_timeout=0, the check is disabled."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=Exception("connection refused"))
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 500,
            'event_count': 1,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        async def _set_done():
            await asyncio.sleep(0.05)
            done.set()
        _background_task = asyncio.create_task(_set_done())  # noqa: RUF006

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=99999,  # Very high to not trigger
            process_output_timeout=0,
            max_ping_failures=999,
        )

        assert result is None  # Should not fire when disabled


class TestCheckToolWatchdog:
    """Tests for _check_tool_watchdog function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_stats(self):
        """Returns None when stats is None."""
        from pokepoke.models.sdk_await import _check_tool_watchdog
        session = AsyncMock()
        result = await _check_tool_watchdog(session, stats=None, tool_call_timeout=600)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_timeout_disabled(self):
        """Returns None when tool_call_timeout <= 0."""
        from pokepoke.models.sdk_await import _check_tool_watchdog
        session = AsyncMock()
        stats: dict = {'tool_start_times': {'t1': time.monotonic()}}
        result = await _check_tool_watchdog(session, stats=stats, tool_call_timeout=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_active_tools(self):
        """Returns None when tool_start_times is empty."""
        from pokepoke.models.sdk_await import _check_tool_watchdog
        session = AsyncMock()
        stats: dict = {'tool_start_times': {}}
        result = await _check_tool_watchdog(session, stats=stats, tool_call_timeout=600)
        assert result is None

    @pytest.mark.asyncio
    async def test_tool_timeout_triggers_abort(self):
        """When a tool exceeds timeout, aborts and returns 'tool_timeout'."""
        from pokepoke.models.sdk_await import _check_tool_watchdog
        session = AsyncMock()
        handler = MagicMock()
        handler._pending_tools = {
            'tool-1': {'name': 'run_tests', 'args': {'path': '/src'}},
        }
        handler._item_logger = MagicMock()
        stats: dict = {
            'tool_start_times': {'tool-1': time.monotonic() - 700},
        }
        result = await _check_tool_watchdog(
            session, stats=stats, tool_call_timeout=600, handler=handler,
        )
        assert result == "tool_timeout"
        session.abort.assert_called_once()
        assert handler._item_logger.log_error.call_count >= 1

    @pytest.mark.asyncio
    async def test_tool_timeout_abort_failure_still_returns(self):
        """If session.abort raises during tool timeout, still returns 'tool_timeout'."""
        from pokepoke.models.sdk_await import _check_tool_watchdog
        session = AsyncMock()
        session.abort.side_effect = Exception("abort failed")
        stats: dict = {
            'tool_start_times': {'tool-1': time.monotonic() - 700},
        }
        result = await _check_tool_watchdog(
            session, stats=stats, tool_call_timeout=600,
        )
        assert result == "tool_timeout"

    @pytest.mark.asyncio
    async def test_tool_not_yet_timed_out(self):
        """When tool is within timeout, returns None."""
        from pokepoke.models.sdk_await import _check_tool_watchdog
        session = AsyncMock()
        stats: dict = {
            'tool_start_times': {'tool-1': time.monotonic()},
        }
        result = await _check_tool_watchdog(
            session, stats=stats, tool_call_timeout=600,
        )
        assert result is None


class TestAwaitCompletionShutdown:
    """Tests for shutdown detection in _await_completion."""

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog.is_shutting_down', return_value=True)
    async def test_shutdown_returns_shutdown(self, mock_shutdown):
        """When is_shutting_down() is True, returns 'shutdown'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
        )

        assert result == "shutdown"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog.is_shutting_down', return_value=True)
    async def test_shutdown_abort_failure_still_returns(self, mock_shutdown):
        """If session.abort raises during shutdown, still returns 'shutdown'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        session.abort.side_effect = OSError("abort failed")
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
        )

        assert result == "shutdown"


class TestAwaitCompletionClientState:
    """Tests for client state detection in _await_completion."""

    @pytest.mark.asyncio
    async def test_disconnected_client_forces_completion(self):
        """When client state is 'disconnected', forces completion."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "disconnected"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
        )

        assert result is None
        assert done.is_set()

    @pytest.mark.asyncio
    async def test_error_client_state_forces_completion(self):
        """When client state is 'error', forces completion."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "error"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
        )

        assert result is None
        assert done.is_set()

    @pytest.mark.asyncio
    async def test_get_state_exception_continues_loop(self):
        """When get_state raises, the loop continues gracefully."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        # First call raises, second returns disconnected to end the test
        client.get_state.side_effect = [Exception("state error"), "disconnected"]
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
        )

        assert result is None


class TestAwaitCompletionTimeout:
    """Tests for max_timeout in _await_completion."""

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout(self):
        """When max_timeout expires, returns 'timeout'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=0.01,
            stats=stats, inactivity_timeout=9999,
        )

        assert result == "timeout"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    async def test_timeout_abort_failure_still_returns(self):
        """If session.abort raises during timeout, still returns 'timeout'."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        session.abort.side_effect = OSError("abort failed")
        client = MagicMock()
        client.get_state.return_value = "running"
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 0,
            'tool_start_times': {},
        }

        result = await _await_completion(
            session, client, done, max_timeout=0.01,
            stats=stats, inactivity_timeout=9999,
        )

        assert result == "timeout"


class TestAwaitCompletionNormalCompletion:
    """Tests for normal completion path (all AND conditions met)."""

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_work_done_no_pending_clean_exit_is_normal_completion(self):
        """When work done, no pending, process exited 0 → normal completion (not process_dead)."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        client.get_state.return_value = "running"
        client.ping = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.poll.return_value = 0
        client._process = mock_process

        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 100,
            'event_count': 50,
            'last_tool_activity_time': 0.0,
            'pending_tool_calls': 0,
            'tool_start_times': {},
            'turn_count': 3,
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=1,
        )

        assert result is None
        session.abort.assert_not_called()


class TestAwaitCompletionEventGapLogging:
    """Tests for event gap diagnostic logging."""

    @pytest.mark.asyncio
    @patch('pokepoke.models.sdk_watchdog._HB_INTERVAL', 0.1)
    async def test_event_gap_logging_fires_for_large_gaps(self):
        """When event gap exceeds 60s, diagnostic logging fires."""
        from pokepoke.models.sdk_helpers import _await_completion

        session = AsyncMock()
        client = MagicMock()
        # End after 2 iterations via disconnected state
        client.get_state.side_effect = ["running", "disconnected"]
        client.ping = AsyncMock()
        done = asyncio.Event()

        stats = {
            'last_event_time': time.monotonic() - 120,
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 1,
            'tool_start_times': {},
            'turn_count': 2,
        }

        result = await _await_completion(
            session, client, done, max_timeout=3600,
            stats=stats, inactivity_timeout=9999,
            max_ping_failures=999,
        )

        assert result is None


class TestProcessLivenessConfig:
    """Tests for process_output_timeout and max_ping_failures config fields."""

    def test_default_values(self):
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        assert cfg.process_output_timeout == 600
        assert cfg.max_ping_failures == 3

    def test_clamped_to_minimum(self):
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig(process_output_timeout=5, max_ping_failures=0)
        assert cfg.process_output_timeout == 30
        assert cfg.max_ping_failures == 1

    def test_custom_values_preserved(self):
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig(process_output_timeout=600, max_ping_failures=5)
        assert cfg.process_output_timeout == 600
        assert cfg.max_ping_failures == 5
