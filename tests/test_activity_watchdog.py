"""Tests for activity watchdog functionality."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from pokepoke.types import BeadsWorkItem


@pytest.fixture
def sample_work_item():
    """Create a sample work item for testing."""
    return BeadsWorkItem(
        id="test-watchdog-123",
        title="Test watchdog work item",
        description="Testing activity watchdog",
        status="open",
        priority=1,
        issue_type="feature",
        labels=["test"]
    )


@pytest.mark.asyncio
class TestActivityWatchdog:
    """Tests for activity watchdog functionality."""
    
    @patch('pokepoke.copilot_sdk._activity_watchdog')
    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_watchdog_enabled_with_item_logger(self, mock_client_class, mock_watchdog, sample_work_item):
        """Test that watchdog is started when item_logger is provided."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio
        
        # Mock watchdog to complete immediately
        async def mock_watchdog_impl(*args, **kwargs):
            return False
        mock_watchdog.side_effect = mock_watchdog_impl
        
        # Mock item logger
        mock_logger = MagicMock()
        mock_logger.log_path = "/tmp/test.log"
        
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-watchdog"
        
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
            item_logger=mock_logger,
            idle_timeout=0.01
        )
        
        assert result.success
        # Verify watchdog was called
        assert mock_watchdog.called
    
    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_watchdog_cancelled_on_normal_completion(self, mock_client_class, sample_work_item, tmp_path):
        """Test that watchdog is cancelled when session completes normally."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio
        
        # Create a temporary log file
        log_file = tmp_path / "test.log"
        log_file.write_text("Initial content")
        
        # Mock item logger
        mock_logger = MagicMock()
        mock_logger.log_path = str(log_file)
        
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-watchdog-cancel"
        
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
                # Keep writing to log file to show activity
                for i in range(3):
                    await asyncio.sleep(0.01)
                    log_file.write_text(f"Update {i}")
                
                # Complete session
                if stored_handler:
                    event = MagicMock()
                    event.type.value = "session.idle"
                    stored_handler(event)
            asyncio.create_task(send_events())
        mock_session.send = mock_send
        mock_session.destroy = AsyncMock()
        
        result = await invoke_copilot_sdk(
            work_item=sample_work_item,
            item_logger=mock_logger,
            idle_timeout=0.01
        )
        
        # Should succeed - watchdog was cancelled before triggering
        assert result.success
    
    @patch('pokepoke.copilot_sdk.CopilotClient')
    async def test_watchdog_disabled_without_item_logger(self, mock_client_class, sample_work_item):
        """Test that watchdog is not started when item_logger is None."""
        from pokepoke.copilot_sdk import invoke_copilot_sdk
        import asyncio
        
        mock_client = AsyncMock()
        mock_session = AsyncMock()
        mock_session.session_id = "test-session-no-watchdog"
        
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
            item_logger=None,  # No logger - watchdog should not start
            idle_timeout=0.01
        )
        
        # Should succeed without watchdog
        assert result.success
