"""Tests for copilot_sdk.py module (direct SDK integration)."""

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from pokepoke.copilot_sdk import (
    build_prompt_from_work_item,
    invoke_copilot_sdk_sync,
    _fail_result,
    _build_token_usage_callback,
    _build_copilot_result,
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

    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_uses_custom_template_name(self, mock_service_class, sample_work_item):
        """Test that a custom template_name from assignment rules is used."""
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Custom template prompt"
        mock_service_class.return_value = mock_service

        result = build_prompt_from_work_item(sample_work_item, template_name="high-pri-feature")

        assert result == "Custom template prompt"
        call_args = mock_service.load_and_render.call_args
        assert call_args[0][0] == "high-pri-feature"

    @patch('pokepoke.copilot_sdk.PromptService')
    def test_build_prompt_defaults_to_beads_item_template(self, mock_service_class, sample_work_item):
        """Test that default template_name is 'beads-item' when none specified."""
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Default prompt"
        mock_service_class.return_value = mock_service

        build_prompt_from_work_item(sample_work_item)

        call_args = mock_service.load_and_render.call_args
        assert call_args[0][0] == "beads-item"


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


class TestCopilotClientNone:
    """Test behavior when CopilotClient SDK is not installed."""

    @patch('pokepoke.copilot_sdk.CopilotClient', None)
    def test_invoke_sync_raises_when_sdk_missing(self, sample_work_item):
        """Test that invoke_copilot_sdk_sync raises ImportError when SDK not installed."""
        with pytest.raises(ImportError, match="copilot.*SDK.*not installed"):
            invoke_copilot_sdk_sync(
                work_item=sample_work_item,
                prompt="test prompt",
            )


@pytest.mark.asyncio
class TestInvokeCopilotSDKAsync:
    """Tests for invoke_copilot_sdk async function."""

    @pytest.fixture(autouse=True)
    def _mock_process_cleanup(self):
        with patch('pokepoke.process_utils.wait_for_process_cleanup'):
            yield

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
                    event.type.value = "session.end"
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
                    event.type.value = "session.end"
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
    async def test_invoke_copilot_sdk_session_end_completes(self, mock_client_class, sample_work_item):
        """Session should complete from session.end event — the explicit agent completion signal."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-turn-end"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()
        mock_client.get_state = MagicMock(return_value="connected")

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
                    # Turn ends but session continues...
                    event = MagicMock()
                    event.type.value = "assistant.turn_end"
                    event.data = MagicMock()
                    stored_handler(event)
                    # Agent explicitly signals done
                    event = MagicMock()
                    event.type.value = "session.end"
                    event.data = MagicMock()
                    stored_handler(event)
            asyncio.create_task(send_events())

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.1,
        )

        assert result.success

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
                    event.type.value = "session.end"
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
                    event.type.value = "session.end"
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
        # Session must be destroyed even on early exit (timeout path)
        mock_session.destroy.assert_called_once()

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_inactivity_destroys_session(self, mock_client_class, sample_work_item):
        """Test that session.destroy() is called on inactivity early exit."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-inactivity"
        mock_session.abort = AsyncMock()

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        mock_client_class.return_value = mock_client

        # _await_completion returns "inactivity" to trigger that path
        with patch('pokepoke.copilot_sdk._await_completion', new_callable=AsyncMock, return_value="inactivity"):
            mock_session.on = lambda handler: None
            mock_session.send = AsyncMock()
            mock_session.destroy = AsyncMock()

            result = await invoke_copilot_sdk(
                work_item=sample_work_item,
                timeout=10.0,
                idle_timeout=0.01
            )

        assert not result.success
        assert "no sdk events" in result.error.lower() or "inactiv" in result.error.lower()
        mock_session.destroy.assert_called_once()

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
                event.type.value = "session.end"
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
                event.type.value = "session.end"
                stored_handler(event)

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        # Don't provide prompt - should generate one with default template
        await invoke_copilot_sdk(
            work_item=sample_work_item,
            idle_timeout=0.01
        )

        mock_build_prompt.assert_called_once_with(sample_work_item, "beads-item")

    @patch('pokepoke.copilot_sdk.CopilotClient')
    @patch('pokepoke.copilot_sdk.build_prompt_from_work_item')
    async def test_invoke_copilot_sdk_with_custom_template_name(
        self, mock_build_prompt, mock_client_class, sample_work_item
    ):
        """Test SDK invocation passes custom template_name to prompt builder."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_build_prompt.return_value = "Custom template prompt"

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-custom-template"

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
                event.type.value = "session.end"
                stored_handler(event)

        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        # Provide custom template_name
        await invoke_copilot_sdk(
            work_item=sample_work_item,
            template_name="bug-item",
            idle_timeout=0.01
        )

        # Verify build_prompt_from_work_item was called with custom template
        mock_build_prompt.assert_called_once_with(sample_work_item, "bug-item")

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
                    event.type.value = "session.end"
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
                    event.type.value = "session.end"
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
                    event.type.value = "session.end"
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
                    event.type.value = "session.end"
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
                    event.type.value = "session.end"
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
                    event.type.value = "session.end"
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
                raise TimeoutError()
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
                    event.type.value = "session.end"
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
    @patch('pokepoke.sdk_helpers.is_shutting_down', return_value=True)
    @patch('pokepoke.copilot_sdk.is_shutting_down', return_value=True)
    async def test_invoke_copilot_sdk_shutdown_during_wait(self, mock_shutting_down, mock_shutting_down_helpers, mock_client_class, sample_work_item):
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
                raise TimeoutError()
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
                    event.type.value = "session.end"
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
    async def test_invoke_copilot_sdk_disconnected_client_forces_completion(self, mock_client_class, sample_work_item):
        """Test SDK detects disconnected client and forces completion instead of hanging."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-disconnect"
        mock_session.abort = AsyncMock()

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        # Simulate the client process dying - get_state returns 'disconnected'
        mock_client.get_state = MagicMock(return_value="disconnected")

        mock_client_class.return_value = mock_client

        mock_session.on = MagicMock()
        mock_session.send = AsyncMock()  # Don't trigger idle
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            timeout=5.0,  # Give enough time for get_state check
            idle_timeout=0.01,
        )

        # Should detect disconnection and force-complete (success with no errors)
        assert result.success

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_error_state_forces_completion(self, mock_client_class, sample_work_item):
        """Test SDK detects error state client and forces completion."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-error-state"
        mock_session.abort = AsyncMock()

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        # Simulate the client entering error state
        mock_client.get_state = MagicMock(return_value="error")

        mock_client_class.return_value = mock_client

        mock_session.on = MagicMock()
        mock_session.send = AsyncMock()
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            timeout=5.0,
            idle_timeout=0.01,
        )

        assert result.success

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_invoke_copilot_sdk_get_state_exception_does_not_crash(self, mock_client_class, sample_work_item):
        """Test that get_state() raising an exception doesn't crash the poll loop."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-get-state-err"

        mock_client.start = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)
        mock_client.stop = AsyncMock()

        # get_state raises — should be silently caught
        mock_client.get_state = MagicMock(side_effect=RuntimeError("transport gone"))

        mock_client_class.return_value = mock_client

        stored_handler = None
        def capture_handler(handler):
            nonlocal stored_handler
            stored_handler = handler
        mock_session.on = capture_handler

        async def mock_send(message):
            async def trigger_idle():
                await asyncio.sleep(0.05)
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.end"
                    stored_handler(event)
            asyncio.create_task(trigger_idle())
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            timeout=5.0,
            idle_timeout=0.01,
        )

        # Should still complete normally despite get_state errors
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


class TestBuildTokenUsageCallback:
    """Tests for _build_token_usage_callback."""

    def test_returns_callable(self):
        callback = _build_token_usage_callback()
        assert callable(callback)

    @patch('pokepoke.sdk_helpers.terminal_ui')
    def test_callback_pushes_tokens_when_agent_id_set(self, mock_ui):
        callback = _build_token_usage_callback()
        mock_thread = MagicMock()
        mock_thread.agent_id = "agent-1"
        with patch('pokepoke.desktop_ui._thread_output', mock_thread):
            callback(100, 50)
        mock_ui.ui.push_agent_tokens.assert_called_once_with("agent-1", 100, 50)

    @patch('pokepoke.sdk_helpers.terminal_ui')
    def test_callback_noop_when_no_agent_id(self, mock_ui):
        callback = _build_token_usage_callback()
        mock_thread = MagicMock(spec=[])  # no agent_id attribute
        with patch('pokepoke.desktop_ui._thread_output', mock_thread):
            callback(100, 50)
        mock_ui.ui.push_agent_tokens.assert_not_called()


class TestBuildCopilotResult:
    """Tests for _build_copilot_result."""

    def _make_stats(self, **overrides):
        defaults = {
            "pending_tool_calls": 0,
            "idle_task": None,
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
            "total_cache_read_tokens": 0,
            "total_cache_write_tokens": 0,
            "turn_count": 3,
            "total_tool_calls": 5,
        }
        defaults.update(overrides)
        return defaults

    def _make_work_item(self):
        return BeadsWorkItem(
            id="wi-1", title="Test", description="", status="open",
            priority=2, issue_type="bug", labels=None,
        )

    def test_success_result(self):
        result = _build_copilot_result(
            work_item=self._make_work_item(),
            output_lines=["line1\n", "line2\n"],
            errors=[],
            stats=self._make_stats(),
            current_model="claude-sonnet-4",
            total_api_duration=10.0,
            total_wall_duration=12.0,
        )
        assert result.success is True
        assert result.output == "line1\nline2\n"
        assert result.error is None
        assert result.work_item_id == "wi-1"
        assert result.stats is not None
        assert result.stats.input_tokens == 1000
        assert result.stats.output_tokens == 500
        assert result.stats.tool_calls == 5
        assert result.model == "claude-sonnet-4"

    def test_failure_result_with_errors(self):
        result = _build_copilot_result(
            work_item=self._make_work_item(),
            output_lines=[],
            errors=["err1", "err2"],
            stats=self._make_stats(turn_count=0, total_input_tokens=0),
            current_model="claude-sonnet-4",
            total_api_duration=1.0,
            total_wall_duration=2.0,
        )
        assert result.success is False
        assert result.error == "err1; err2"

    def test_empty_output(self):
        result = _build_copilot_result(
            work_item=self._make_work_item(),
            output_lines=[],
            errors=[],
            stats=self._make_stats(turn_count=0, total_input_tokens=0),
            current_model="m",
            total_api_duration=0.0,
            total_wall_duration=0.0,
        )
        assert result.success is True
        assert result.output == ""


@pytest.mark.asyncio
class TestRateLimitFallback:
    """Tests for RateLimitError fallback to FALLBACK_MODEL."""

    @pytest.fixture(autouse=True)
    def _mock_process_cleanup(self):
        with patch('pokepoke.process_utils.wait_for_process_cleanup'):
            yield

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_rate_limit_triggers_fallback_to_fallback_model(
        self, mock_client_class, sample_work_item
    ):
        """RateLimitError on first attempt retries with FALLBACK_MODEL."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        from pokepoke.config import FALLBACK_MODEL

        mock_client = AsyncMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()

        attempt_count = 0
        sessions_created = []
        configs_captured = []

        async def mock_create_session(config):
            nonlocal attempt_count
            attempt_count += 1
            configs_captured.append(dict(config))
            mock_session = AsyncMock()
            mock_session.session_id = f"session-attempt-{attempt_count}"
            mock_session.destroy = AsyncMock()
            sessions_created.append(mock_session)

            stored_handler = None
            def mock_on(handler):
                nonlocal stored_handler
                stored_handler = handler
            mock_session.on = mock_on

            async def mock_send(message):
                async def send_events():
                    await asyncio.sleep(0.01)
                    if stored_handler:
                        if attempt_count == 1:
                            # First attempt: rate limit error
                            event = MagicMock()
                            event.type.value = "session.error"
                            event.data = MagicMock(
                                message="rate limit exceeded"
                            )
                            stored_handler(event)
                        else:
                            # Second attempt: success
                            event = MagicMock()
                            event.type.value = "assistant.message_delta"
                            event.data = MagicMock(delta_content="Fallback OK")
                            stored_handler(event)
                            event = MagicMock()
                            event.type.value = "session.end"
                            event.data = MagicMock()
                            stored_handler(event)
                asyncio.create_task(send_events())

            mock_session.send = mock_send
            return mock_session

        mock_client.create_session = mock_create_session
        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01,
        )

        assert result.success
        assert "Fallback OK" in result.output
        assert attempt_count == 2
        assert configs_captured[0]["model"] != FALLBACK_MODEL
        assert configs_captured[1]["model"] == FALLBACK_MODEL
        # First session should have been destroyed before fallback
        sessions_created[0].destroy.assert_called()

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_rate_limit_fallback_model_set_in_result(
        self, mock_client_class, sample_work_item
    ):
        """After fallback, result.model should be FALLBACK_MODEL."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        from pokepoke.config import FALLBACK_MODEL

        mock_client = AsyncMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()

        attempt_count = 0

        async def mock_create_session(config):
            nonlocal attempt_count
            attempt_count += 1
            mock_session = AsyncMock()
            mock_session.session_id = f"session-{attempt_count}"
            mock_session.destroy = AsyncMock()

            stored_handler = None
            def mock_on(handler):
                nonlocal stored_handler
                stored_handler = handler
            mock_session.on = mock_on

            async def mock_send(message):
                async def send_events():
                    await asyncio.sleep(0.01)
                    if stored_handler:
                        if attempt_count == 1:
                            event = MagicMock()
                            event.type.value = "session.error"
                            event.data = MagicMock(
                                message="rate limit hit"
                            )
                            stored_handler(event)
                        else:
                            event = MagicMock()
                            event.type.value = "session.end"
                            event.data = MagicMock()
                            stored_handler(event)
                asyncio.create_task(send_events())

            mock_session.send = mock_send
            return mock_session

        mock_client.create_session = mock_create_session
        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01,
        )

        assert result.success
        assert result.model == FALLBACK_MODEL

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_rate_limit_handler_reset_for_retry(
        self, mock_client_class, sample_work_item
    ):
        """Handler state (output, errors) is reset between fallback attempts."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()

        attempt_count = 0

        async def mock_create_session(config):
            nonlocal attempt_count
            attempt_count += 1
            mock_session = AsyncMock()
            mock_session.session_id = f"session-{attempt_count}"
            mock_session.destroy = AsyncMock()

            stored_handler = None
            def mock_on(handler):
                nonlocal stored_handler
                stored_handler = handler
            mock_session.on = mock_on

            async def mock_send(message):
                async def send_events():
                    await asyncio.sleep(0.01)
                    if stored_handler:
                        if attempt_count == 1:
                            # Emit some output, then rate limit
                            event = MagicMock()
                            event.type.value = "assistant.message_delta"
                            event.data = MagicMock(
                                delta_content="partial before rate limit"
                            )
                            stored_handler(event)
                            event = MagicMock()
                            event.type.value = "session.error"
                            event.data = MagicMock(
                                message="rate limit exceeded"
                            )
                            stored_handler(event)
                        else:
                            event = MagicMock()
                            event.type.value = "assistant.message_delta"
                            event.data = MagicMock(
                                delta_content="clean fallback output"
                            )
                            stored_handler(event)
                            event = MagicMock()
                            event.type.value = "session.end"
                            event.data = MagicMock()
                            stored_handler(event)
                asyncio.create_task(send_events())

            mock_session.send = mock_send
            return mock_session

        mock_client.create_session = mock_create_session
        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01,
        )

        assert result.success
        # Output should only contain fallback attempt content (cleared on retry)
        assert "partial before rate limit" not in result.output
        assert "clean fallback output" in result.output

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_rate_limit_on_fallback_model_breaks_with_error(
        self, mock_client_class, sample_work_item
    ):
        """Rate limit on FALLBACK_MODEL itself should not retry — breaks with error."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        from pokepoke.config import FALLBACK_MODEL

        mock_client = AsyncMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()

        attempt_count = 0

        async def mock_create_session(config):
            nonlocal attempt_count
            attempt_count += 1
            mock_session = AsyncMock()
            mock_session.session_id = f"session-{attempt_count}"
            mock_session.destroy = AsyncMock()

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
                        event.type.value = "session.error"
                        event.data = MagicMock(
                            message="rate limit exceeded"
                        )
                        stored_handler(event)
                asyncio.create_task(send_events())

            mock_session.send = mock_send
            return mock_session

        mock_client.create_session = mock_create_session
        mock_client_class.return_value = mock_client

        # Start with FALLBACK_MODEL directly — no further fallback possible
        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            model=FALLBACK_MODEL,
            idle_timeout=0.01,
        )

        assert not result.success
        assert "Rate limit exceeded" in result.error
        # Should NOT have retried — only 1 session created
        assert attempt_count == 1

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_rate_limit_session_destroy_failure_still_falls_back(
        self, mock_client_class, sample_work_item
    ):
        """Fallback proceeds even if session.destroy() fails during cleanup."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        from pokepoke.config import FALLBACK_MODEL

        mock_client = AsyncMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()

        attempt_count = 0

        async def mock_create_session(config):
            nonlocal attempt_count
            attempt_count += 1
            mock_session = AsyncMock()
            mock_session.session_id = f"session-{attempt_count}"

            if attempt_count == 1:
                # First session: destroy raises
                mock_session.destroy = AsyncMock(
                    side_effect=RuntimeError("destroy failed")
                )
            else:
                mock_session.destroy = AsyncMock()

            stored_handler = None
            def mock_on(handler):
                nonlocal stored_handler
                stored_handler = handler
            mock_session.on = mock_on

            async def mock_send(message):
                async def send_events():
                    await asyncio.sleep(0.01)
                    if stored_handler:
                        if attempt_count == 1:
                            event = MagicMock()
                            event.type.value = "session.error"
                            event.data = MagicMock(
                                message="rate limit exceeded"
                            )
                            stored_handler(event)
                        else:
                            event = MagicMock()
                            event.type.value = "session.end"
                            event.data = MagicMock()
                            stored_handler(event)
                asyncio.create_task(send_events())

            mock_session.send = mock_send
            return mock_session

        mock_client.create_session = mock_create_session
        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01,
        )

        # Fallback succeeds despite destroy() failure on first session
        assert result.success
        assert attempt_count == 2
        assert result.model == FALLBACK_MODEL

    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_rate_limit_both_attempts_exhausted(
        self, mock_client_class, sample_work_item
    ):
        """Rate limit on both attempts results in failure, not infinite loop."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk

        mock_client = AsyncMock()
        mock_client.start = AsyncMock()
        mock_client.stop = AsyncMock()

        attempt_count = 0

        async def mock_create_session(config):
            nonlocal attempt_count
            attempt_count += 1
            mock_session = AsyncMock()
            mock_session.session_id = f"session-{attempt_count}"
            mock_session.destroy = AsyncMock()

            stored_handler = None
            def mock_on(handler):
                nonlocal stored_handler
                stored_handler = handler
            mock_session.on = mock_on

            async def mock_send(message):
                async def send_events():
                    await asyncio.sleep(0.01)
                    if stored_handler:
                        # Both attempts hit rate limit
                        event = MagicMock()
                        event.type.value = "session.error"
                        event.data = MagicMock(
                            message="rate limit exceeded"
                        )
                        stored_handler(event)
                asyncio.create_task(send_events())

            mock_session.send = mock_send
            return mock_session

        mock_client.create_session = mock_create_session
        mock_client_class.return_value = mock_client

        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            prompt="Test prompt",
            idle_timeout=0.01,
        )

        assert not result.success
        assert "Rate limit exceeded" in result.error
        # Exactly 2 attempts: original + one fallback (no infinite loop)
        assert attempt_count == 2


@pytest.mark.asyncio
class TestAwaitCompletionAbortOSError:
    """Tests that _await_completion handles OSError during session.abort() gracefully."""

    async def test_shutdown_abort_oserror_returns_shutdown(self):
        """When session.abort() raises OSError on shutdown, still return 'shutdown'."""
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_session.abort = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=True):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=300.0,
            )

        assert result == "shutdown"
        mock_session.abort.assert_called_once()

    async def test_timeout_abort_oserror_returns_timeout(self):
        """When session.abort() raises OSError on timeout, still return 'timeout'."""
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_session.abort = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=0.0,  # Immediate timeout
            )

        assert result == "timeout"
        mock_session.abort.assert_called_once()

    async def test_inactivity_abort_oserror_returns_inactivity(self):
        """When session.abort() raises OSError on inactivity, still return 'inactivity'."""
        import time
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_session.abort = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()
        stats = {
            'last_event_time': time.monotonic() - 700,
            'event_count': 5,
            'last_tool_activity_time': time.monotonic() - 700,
        }

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=300.0,
                stats=stats,
                inactivity_timeout=600.0,
            )

        assert result == "inactivity"
        mock_session.abort.assert_called_once()

    async def test_shutdown_abort_success_returns_shutdown(self):
        """Normal shutdown abort (no error) still returns 'shutdown'."""
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_session.abort = AsyncMock()

        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=True):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=300.0,
            )

        assert result == "shutdown"
        mock_session.abort.assert_called_once()

    async def test_timeout_abort_success_returns_timeout(self):
        """Normal timeout abort (no error) still returns 'timeout'."""
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_session.abort = AsyncMock()

        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=0.0,  # Immediate timeout
            )

        assert result == "timeout"
        mock_session.abort.assert_called_once()

    async def test_inactivity_skipped_when_pending_tool_calls(self):
        """Inactivity timeout must NOT fire when pending_tool_calls > 0.

        Long-running tools (e.g. git commit triggering pre-commit hooks)
        produce zero SDK events.  The inactivity detector should stay
        quiet while tools are still executing.
        """
        import time
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()
        # Simulate: last event was 700s ago BUT a tool call is pending
        stats = {
            'last_event_time': time.monotonic() - 700,
            'event_count': 5,
            'last_tool_activity_time': time.monotonic() - 700,
            'pending_tool_calls': 1,
        }

        # Use a very short max_timeout so the loop terminates via timeout
        # rather than inactivity — proving inactivity was skipped.
        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=0.0,
                stats=stats,
                inactivity_timeout=600.0,
            )

        # Should hit the hard timeout, NOT inactivity
        assert result == "timeout"

    async def test_inactivity_fires_when_zero_pending_tool_calls(self):
        """Inactivity timeout fires normally when no tools are pending."""
        import time
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()
        stats = {
            'last_event_time': time.monotonic() - 700,
            'event_count': 5,
            'last_tool_activity_time': time.monotonic() - 700,
            'pending_tool_calls': 0,
        }

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=300.0,
                stats=stats,
                inactivity_timeout=600.0,
            )

        assert result == "inactivity"

    async def test_tool_timeout_fires_when_tool_exceeds_limit(self):
        """Tool call watchdog fires when a single tool exceeds the timeout."""
        import time
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()
        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 1,
            'tool_start_times': {'tool-abc': time.monotonic() - 700},
        }

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=300.0,
                stats=stats,
                inactivity_timeout=600.0,
                tool_call_timeout=600.0,
            )

        assert result == "tool_timeout"
        mock_session.abort.assert_called_once()

    async def test_tool_timeout_does_not_fire_when_within_limit(self):
        """Tool call watchdog does not fire when tools are within the timeout."""
        import time
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()
        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 1,
            'tool_start_times': {'tool-abc': time.monotonic() - 10},
        }

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=0.0,
                stats=stats,
                inactivity_timeout=600.0,
                tool_call_timeout=600.0,
            )

        # Should hit the hard timeout, NOT tool_timeout
        assert result == "timeout"

    async def test_tool_timeout_abort_oserror_returns_tool_timeout(self):
        """When session.abort() raises OSError on tool timeout, still return 'tool_timeout'."""
        import time
        from pokepoke.sdk_helpers import _await_completion

        mock_session = AsyncMock()
        mock_session.abort = AsyncMock(side_effect=OSError(22, "Invalid argument"))

        mock_client = MagicMock()
        mock_client.get_state = MagicMock(return_value="connected")

        done = asyncio.Event()
        stats = {
            'last_event_time': time.monotonic(),
            'event_count': 5,
            'last_tool_activity_time': time.monotonic(),
            'pending_tool_calls': 1,
            'tool_start_times': {'tool-xyz': time.monotonic() - 700},
        }

        with patch('pokepoke.sdk_helpers.is_shutting_down', return_value=False):
            result = await _await_completion(
                mock_session, mock_client, done,
                max_timeout=300.0,
                stats=stats,
                inactivity_timeout=600.0,
                tool_call_timeout=600.0,
            )

        assert result == "tool_timeout"
        mock_session.abort.assert_called_once()
