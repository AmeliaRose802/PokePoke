"""Tests for copilot_sdk.py module (direct SDK integration)."""

import pytest
import subprocess
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from pokepoke.copilot import get_allowed_directories
from pokepoke.copilot_sdk import (
    build_prompt_from_work_item,
    invoke_copilot_sdk_sync
)
from pokepoke.types import BeadsWorkItem


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


class TestGetAllowedDirectoriesSDK:
    """Tests for get_allowed_directories function in SDK module."""
    
    @patch('pokepoke.copilot.subprocess.run')
    @patch('pokepoke.copilot.os.getcwd')
    def test_allowed_directories_with_git(self, mock_getcwd, mock_run):
        """Test allowed directories when git command succeeds."""
        mock_getcwd.return_value = "/current/dir"
        mock_run.return_value = MagicMock(
            stdout=".git\n",
            returncode=0
        )
        
        result = get_allowed_directories()
        
        assert "/current/dir" in result
        assert len(result) >= 1
    
    @patch('pokepoke.copilot.subprocess.run')
    @patch('pokepoke.copilot.os.getcwd')
    def test_allowed_directories_git_fails(self, mock_getcwd, mock_run):
        """Test allowed directories when git command fails."""
        mock_getcwd.return_value = "/current/dir"
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        
        result = get_allowed_directories()
        
        # Should still return current directory
        assert result == ["/current/dir"]
    
    @patch('pokepoke.copilot.subprocess.run')
    @patch('pokepoke.copilot.os.getcwd')
    def test_allowed_directories_different_root(self, mock_getcwd, mock_run):
        """Test when worktree directory differs from repo root."""
        mock_getcwd.return_value = "/worktree/dir"
        mock_run.return_value = MagicMock(
            stdout="/repo/.git\n",
            returncode=0
        )
        
        result = get_allowed_directories()
        
        # Should contain both worktree and repo root
        assert "/worktree/dir" in result


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
        mock_asyncio_run.return_value = mock_result
        
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
        mock_asyncio_run.return_value = mock_result
        
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
            prompt="Test prompt"
        )
        
        assert result.work_item_id == sample_work_item.id
        assert result.success
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
            prompt="Test prompt"
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
            work_item=sample_work_item
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
            work_item=sample_work_item
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
            work_item=sample_work_item
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
            timeout=0.1  # Very short timeout
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
            work_item=sample_work_item
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
            work_item=sample_work_item
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
        
        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            deny_write=True
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
        result = await invoke_copilot_sdk(
            work_item=sample_work_item
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
            work_item=sample_work_item
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
            work_item=sample_work_item
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
            work_item=sample_work_item
        )
        
        assert not result.success
        assert "Interrupted by user" in result.error
    
    @patch('pokepoke.copilot_sdk.CopilotClient')
    @patch('pokepoke.copilot_sdk.os.environ', new_callable=dict)
    async def test_invoke_copilot_sdk_environment_handling(self, mock_environ, mock_client_class, sample_work_item):
        """Test SDK invocation handles PYTHONIOENCODING environment variable."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio
        
        # Start with original value
        mock_environ['PYTHONIOENCODING'] = 'utf-8'
        
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
            work_item=sample_work_item
        )
        
        assert result.success
        # Environment should be restored to original value
        assert mock_environ.get('PYTHONIOENCODING') == 'utf-8'
    
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
            work_item=sample_work_item
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
            work_item=sample_work_item
        )
        
        assert not result.success
        assert "Interrupted by user" in result.error
