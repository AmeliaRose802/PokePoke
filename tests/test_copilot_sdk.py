"""Tests for copilot_sdk.py module (direct SDK integration)."""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from pokepoke.copilot_sdk import (
    build_prompt_from_work_item,
    invoke_copilot_sdk_sync,
    _fail_result,
    _activity_watchdog,
)
from pokepoke.types import BeadsWorkItem


class TestBuildPromptFromWorkItem:
    """Tests for build_prompt_from_work_item function."""

    def test_build_prompt_from_work_item_real(self, sample_work_item):
        """Test building prompt from work item without mocking."""
        result = build_prompt_from_work_item(sample_work_item)

        # Verify the result contains work item details
        assert sample_work_item.id in result
        assert sample_work_item.title in result
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_prompt_without_labels_real(self):
        """Test building prompt for work item without labels."""
        work_item = BeadsWorkItem(
            id="test-456",
            title="No labels",
            description="Test description",
            status="open",
            priority=2,
            issue_type="bug",
            labels=None
        )

        result = build_prompt_from_work_item(work_item)

        assert work_item.id in result
        assert work_item.title in result
        assert isinstance(result, str)

    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_from_work_item(self, mock_service_class, sample_work_item):
        """Test building prompt from work item."""
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Rendered prompt"
        mock_service_class.return_value = mock_service

        result = build_prompt_from_work_item(sample_work_item)

        assert result == "Rendered prompt"
        mock_service.load_and_render.assert_called_once()
        call_args = mock_service.load_and_render.call_args
        assert call_args[0][0] == "beads-item"
        variables = call_args[0][1]
        assert variables["item_id"] == "test-123"
        assert variables["title"] == "Test work item"

    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_without_labels(self, mock_service_class):
        """Test building prompt for work item without labels."""
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Prompt"
        mock_service_class.return_value = mock_service

        work_item = BeadsWorkItem(
            id="test-456",
            title="No labels",
            description="Test",
            status="open",
            priority=2,
            issue_type="bug",
            labels=None
        )

        result = build_prompt_from_work_item(work_item)

        assert result == "Prompt"
        call_args = mock_service.load_and_render.call_args
        variables = call_args[0][1]
        assert variables["labels"] is None


class TestInvokeCopilotSDKSync:
    """Tests for invoke_copilot_sdk_sync function signature."""

    @patch('pokepoke.copilot_sdk.asyncio.run')
    def test_invoke_copilot_sdk_sync_with_item_logger(
        self, mock_asyncio_run, sample_work_item
    ):
        """Test that invoke_copilot_sdk_sync accepts item_logger parameter."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "Test output"

        def _fake_run(coro):
            coro.close()
            return mock_result

        mock_asyncio_run.side_effect = _fake_run

        # Create a mock logger
        mock_logger = MagicMock()

        # Call the function with item_logger parameter - should not raise TypeError
        result = invoke_copilot_sdk_sync(
            work_item=sample_work_item,
            item_logger=mock_logger
        )

        # Verify function accepts the parameter and completed
        assert result == mock_result
        assert mock_asyncio_run.called

    @patch('pokepoke.copilot_sdk.asyncio.run')
    def test_invoke_copilot_sdk_sync_with_custom_prompt(
        self, mock_asyncio_run, sample_work_item
    ):
        """Test invoke_copilot_sdk_sync with custom prompt."""
        from pokepoke.types import CopilotResult

        mock_result = CopilotResult(
            work_item_id=sample_work_item.id,
            success=True,
            output="Custom prompt result"
        )
        def _fake_run(coro):
            coro.close()
            return mock_result

        mock_asyncio_run.side_effect = _fake_run

        result = invoke_copilot_sdk_sync(
            work_item=sample_work_item,
            prompt="Custom test prompt"
        )

        assert result.success
        assert result.work_item_id == sample_work_item.id
        mock_asyncio_run.assert_called_once()


@pytest.mark.asyncio
class TestInvokeCopilotSDKAsync:
    """Tests for invoke_copilot_sdk async function."""

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_success(self, mock_client_class, sample_work_item):
        """Test successful SDK invocation."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        # Create mock client and session
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-123"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        # Store the event handler so we can trigger events
        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        # Mock send to trigger session completion after a short delay
        async def mock_send(message):
            # Schedule completion event on next event loop iteration
            async def trigger_completion():
                await asyncio.sleep(0.01)  # Small delay to allow event loop
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.idle"
                    event.data = MagicMock()
                    stored_handler(event)
            asyncio.create_task(trigger_completion())
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01,
        )

        assert result.work_item_id == sample_work_item.id
        assert result.success
        assert result.stats is not None
        assert result.stats.api_duration == pytest.approx(0.0, abs=1.0)
        assert result.stats.wall_duration == pytest.approx(0.0, abs=1.0)
        mock_client.start.assert_called_once()
        mock_client.create_session.assert_called_once()
        mock_client.stop.assert_called_once()

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_message_delta(self, mock_client_class, sample_work_item):
        """Test SDK invocation with streaming message deltas."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-456"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            # Simulate streaming deltas with async events
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    # Send message deltas
                    for chunk in ["Hello ", "world", "!"]:
                        event = MagicMock()
                        event.type.value = "assistant.message_delta"
                        event.data = MagicMock(delta_content=chunk)
                        stored_handler(event)

                    # Send completion event
                    event = MagicMock()
                    event.type.value = "session.idle"
                    event.data = MagicMock()
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01
        )

        assert result.success
        assert result.output == "Hello world!"

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_complete_message(self, mock_client_class, sample_work_item):
        """Test SDK invocation with complete message (no deltas)."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-789"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    # Send complete message (no deltas)
                    event = MagicMock()
                    event.type.value = "assistant.message"
                    event.data = MagicMock(content="Complete message content")
                    stored_handler(event)

                    # Send completion
                    event = MagicMock()
                    event.type.value = "session.idle"
                    event.data = MagicMock()
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success
        assert result.output == "Complete message content"

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_tool_calls(self, mock_client_class, sample_work_item):
        """Test SDK invocation with tool calls."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-tool"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    # Tool call event
                    event = MagicMock()
                    event.type.value = "tool.call"
                    event.data = MagicMock(tool_name="read_file")
                    stored_handler(event)

                    # Tool result event
                    event = MagicMock()
                    event.type.value = "tool.result"
                    event.data = MagicMock(tool_name="read_file", result_type="success")
                    stored_handler(event)

                    # Completion
                    event = MagicMock()
                    event.type.value = "session.idle"
                    event.data = MagicMock()
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_error(self, mock_client_class, sample_work_item):
        """Test SDK invocation with session error."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-error"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    # Send error event
                    event = MagicMock()
                    event.type.value = "session.error"
                    event.data = MagicMock(message="Test error message")
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert not result.success
        assert "Test error message" in result.error

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_timeout(self, mock_client_class, sample_work_item):
        """Test SDK invocation with timeout."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-timeout"
        mock_session.abort = AsyncMock()

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        # Don't trigger any completion events - will timeout
        mock_session.on = lambda handler: None
        mock_session.send = AsyncMock()
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            timeout=0.1,  # Very short timeout
            idle_timeout=0.01
        )

        assert not result.success
        assert "timeout" in result.error.lower()
        mock_session.abort.assert_called_once()

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_exception(self, mock_client_class, sample_work_item):
        """Test SDK invocation with exception during execution."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_client.start = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert not result.success
        assert "Connection failed" in result.error
        mock_client.stop.assert_called_once()

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_stop_exception(self, mock_client_class, sample_work_item):
        """Test SDK invocation when client.stop() raises exception."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_client.start = AsyncMock(side_effect=Exception("Start failed"))
        mock_client.stop = AsyncMock(side_effect=Exception("Stop failed"))

        mock_client_class.return_value = mock_client

        # Should not raise - exception in stop should be caught
        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert not result.success

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_deny_write(self, mock_client_class, sample_work_item):
        """Test SDK invocation with deny_write flag."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-deny"

        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()

        # Capture the config passed to create_session
        captured_config = None
        async def capture_config(config):
            nonlocal captured_config
            captured_config = config
            return mock_session

        mock_client.create_session = capture_config
        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            if stored_handler:
                event = MagicMock()
                event.type.value = "session.idle"
                stored_handler(event)

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        await invoke_copilot_sdk(
            work_item=sample_work_item,
            deny_write=True,
            idle_timeout=0.01
        )

        # Verify deny_write added excluded_tools
        assert captured_config is not None
        assert "excluded_tools" in captured_config
        assert "write" in captured_config["excluded_tools"]
        assert "edit" in captured_config["excluded_tools"]

    @patch('pokepoke.copilot_sdk.CopilotClient')
    @patch('pokepoke.copilot_sdk.build_prompt_from_work_item')
    async def test_invoke_copilot_sdk_generates_prompt_when_not_provided(
        self, mock_build_prompt, mock_client_class, sample_work_item
    ):
        """Test SDK invocation generates prompt when not provided."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_build_prompt.return_value = "Generated prompt"

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-gen"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            if stored_handler:
                event = MagicMock()
                event.type.value = "session.idle"
                stored_handler(event)

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        # Don't provide prompt - should generate one
        await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        mock_build_prompt.assert_called_once_with(sample_work_item)

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_tool_execution(self, mock_client_class, sample_work_item):
        """Test SDK invocation with tool execution events."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-tool-exec"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    # Tool execution start
                    event = MagicMock()
                    event.type.value = "tool.execution_start"
                    event.data = MagicMock(
                        tool_name="read_file",
                        arguments={"path": "/test/file.txt"}
                    )
                    stored_handler(event)

                    # Tool execution complete with result
                    event = MagicMock()
                    event.type.value = "tool.execution_complete"
                    result_obj = MagicMock()
                    result_obj.content = "File content here"
                    event.data = MagicMock(
                        tool_call_id="call-123",
                        result=result_obj,
                        success=True
                    )
                    stored_handler(event)

                    # Completion
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success
        assert "[Tool] read_file" in result.output
        assert "[Result]" in result.output

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_usage_statistics(self, mock_client_class, sample_work_item):
        """Test SDK invocation with usage statistics tracking."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-stats"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    # Usage statistics
                    event = MagicMock()
                    event.type.value = "assistant.usage"
                    event.data = MagicMock(
                        input_tokens=100,
                        output_tokens=50,
                        cache_read_tokens=20,
                        cache_write_tokens=10,
                        cost=0.0042
                    )
                    stored_handler(event)

                    # Turn end
                    event = MagicMock()
                    event.type.value = "assistant.turn_end"
                    stored_handler(event)

                    # Completion
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_keyboard_interrupt_during_wait(self, mock_client_class, sample_work_item):
        """Test SDK invocation with keyboard interrupt during wait."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-interrupt"
        mock_session.abort = AsyncMock()

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        # Simulate keyboard interrupt during send
        async def mock_send(message):
            await asyncio.sleep(0.01)
            raise KeyboardInterrupt("User interrupted")

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert not result.success
        assert "Interrupted by user" in result.error

    @patch('pokepoke.copilot_sdk.CopilotClient')
    @patch('pokepoke.copilot_sdk.os.environ', new_callable=dict)
    async def test_invoke_copilot_sdk_environment_handling(self, mock_environ, mock_client_class, sample_work_item):
        """Test SDK invocation passes PYTHONIOENCODING via client options without mutating global os.environ."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        # Start with original value
        mock_environ['PYTHONIOENCODING'] = 'utf-8'
        original_value = mock_environ['PYTHONIOENCODING']

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-env"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success

        # Verify os.environ was never mutated (remains at original value)
        assert mock_environ.get('PYTHONIOENCODING') == original_value

        # Verify CopilotClient was called with env parameter containing PYTHONIOENCODING
        mock_client_class.assert_called_once()
        call_args = mock_client_class.call_args[0][0]
        assert 'env' in call_args
        assert call_args['env']['PYTHONIOENCODING'] == 'utf-8:replace'

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_tool_requests(self, mock_client_class, sample_work_item):
        """Test SDK invocation with tool requests in assistant message."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-tool-requests"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    # Message with tool requests
                    event = MagicMock()
                    event.type.value = "assistant.message"
                    event.data = MagicMock(
                        content="Let me read that file",
                        tool_requests=[{"tool": "read_file", "args": {}}]
                    )
                    stored_handler(event)

                    # Completion
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success
        assert "Let me read that file" in result.output

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_keyboard_interrupt_outer(self, mock_client_class, sample_work_item):
        """Test SDK invocation with keyboard interrupt in outer try block."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_client.start = AsyncMock(side_effect=KeyboardInterrupt("User interrupted"))
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert not result.success
        assert "Interrupted by user" in result.error

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_with_cwd(self, mock_client_class, sample_work_item):
        """Test SDK invocation passes cwd to client options."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-cwd"
        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()
        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            cwd="/tmp/test-worktree",
            idle_timeout=0.01
        )

        assert result.success
        call_args = mock_client_class.call_args[0][0]
        assert call_args["cwd"] == "/tmp/test-worktree"

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_unicode_decode_error_in_stop(self, mock_client_class, sample_work_item):
        """Test SDK handles UnicodeDecodeError during client.stop()."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-unicode"
        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock(side_effect=UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid'))
        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_general_exception(self, mock_client_class, sample_work_item):
        """Test SDK handles general exceptions during execution."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_client.start = AsyncMock(side_effect=RuntimeError("Connection failed"))
        mock_client.stop = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert not result.success
        assert "SDK exception: Connection failed" in result.error

    @patch('pokepoke.copilot_sdk.is_shutting_down', return_value=True)
    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_keyboard_interrupt_during_shutdown(self, mock_client_class, mock_shutting_down, sample_work_item):
        """Test SDK reports shutdown error when KeyboardInterrupt occurs during shutdown."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_client.start = AsyncMock(side_effect=KeyboardInterrupt("shutdown"))
        mock_client.stop = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert not result.success
        assert "shutdown" in result.error.lower()

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_stop_timeout(self, mock_client_class, sample_work_item):
        """Test SDK handles timeout during client.stop() in finally block."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-stop-timeout"
        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)

        stop_call_count = 0
        async def mock_stop():
            nonlocal stop_call_count
            stop_call_count += 1
            if stop_call_count == 1:
                raise asyncio.TimeoutError()
        mock_client.stop = mock_stop
        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success

    @patch('pokepoke.copilot_sdk.CopilotClient')
    @patch('pokepoke.copilot_sdk.is_shutting_down', return_value=True)
    async def test_invoke_copilot_sdk_shutdown_during_wait(self, mock_shutting_down, mock_client_class, sample_work_item):
        """Test SDK handles shutdown signal during wait loop."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-shutdown-wait"
        mock_session.abort = AsyncMock()

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        mock_session.on = MagicMock()

        async def mock_send(message):
            pass  # Don't trigger idle - let shutdown check fire
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01,
        )

        assert not result.success
        assert "shutdown" in result.error.lower()
        mock_session.abort.assert_called_once()

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_stop_timeout_force_fails(self, mock_client_class, sample_work_item):
        """Test SDK handles exception during forced stop after timeout."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-force-fail"
        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)

        stop_call_count = 0
        async def mock_stop():
            nonlocal stop_call_count
            stop_call_count += 1
            if stop_call_count == 1:
                raise asyncio.TimeoutError()
            raise RuntimeError("Force stop failed")
        mock_client.stop = mock_stop
        mock_client_class.return_value = mock_client

        stored_handler = None
        def mock_on(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = mock_on

        async def mock_send(message):
            async def send_events():
                await asyncio.sleep(0.01)
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        assert result.success

@pytest.mark.asyncio
class TestAPIStatsIntegration:
    """Tests for API duration stats integration."""

    def test_parse_agent_stats_import(self):
        """Test that parse_agent_stats is properly imported and accessible."""
        from pokepoke.stats import parse_agent_stats
        from pokepoke.types import AgentStats

        # Test with sample output
        output = "Total duration (API): 5.0s\nTotal duration (wall): 10.0s"
        result = parse_agent_stats(output)

        assert isinstance(result, AgentStats)
        assert result.api_duration == 5.0
        assert result.wall_duration == 10.0


class TestFailResult:
    """Tests for _fail_result helper."""

    def test_fail_result_returns_failed_copilot_result(self):
        result = _fail_result("item-123", "something broke")
        assert result.work_item_id == "item-123"
        assert result.success is False
        assert result.error == "something broke"
        assert result.attempt_count == 1

    def test_fail_result_with_empty_error(self):
        result = _fail_result("x", "")
        assert result.success is False
        assert result.error == ""


class TestActivityWatchdog:
    """Tests for _activity_watchdog."""

    @pytest.mark.asyncio
    async def test_watchdog_cancellation_returns_false(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("initial")
        abort = asyncio.Event()

        task = asyncio.create_task(
            _activity_watchdog(log_file, timeout_seconds=60, check_interval_seconds=0.05, abort_event=abort)
        )
        await asyncio.sleep(0.02)
        task.cancel()
        result = await task
        assert result is False

    @pytest.mark.asyncio
    async def test_watchdog_triggers_on_idle(self, tmp_path):
        log_file = tmp_path / "test.log"
        log_file.write_text("initial")
        abort = asyncio.Event()

        result = await _activity_watchdog(
            log_file, timeout_seconds=0.05, check_interval_seconds=0.02, abort_event=abort
        )
        assert result is True
        assert abort.is_set()

    @pytest.mark.asyncio
    async def test_watchdog_handles_missing_log_file(self, tmp_path):
        log_file = tmp_path / "nonexistent.log"
        abort = asyncio.Event()

        result = await _activity_watchdog(
            log_file, timeout_seconds=0.05, check_interval_seconds=0.02, abort_event=abort
        )
        assert result is True
        assert abort.is_set()
