"""Tests for PokePoke desktop bridge (WebSocket server)."""

import asyncio
import json
import threading
import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Check if websockets is available
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


# Skip all tests if websockets isn't installed
pytestmark = pytest.mark.skipif(
    not HAS_WEBSOCKETS,
    reason="websockets package not installed"
)


class TestDesktopBridgeInit:
    """Test DesktopBridge initialization."""

    def test_init_default_port(self):
        from pokepoke.desktop_bridge import DesktopBridge, DEFAULT_WS_PORT
        bridge = DesktopBridge()
        assert bridge._port == DEFAULT_WS_PORT
        assert bridge.is_running is False
        assert bridge.client_count == 0

    def test_init_custom_port(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge(port=9999)
        assert bridge._port == 9999

    def test_init_without_websockets_raises(self):
        """Importing without websockets should raise ImportError."""
        from pokepoke.desktop_bridge import DesktopBridge
        with patch("pokepoke.desktop_bridge.HAS_WEBSOCKETS", False):
            with pytest.raises(ImportError, match="websockets"):
                DesktopBridge()


class TestDesktopBridgeState:
    """Test state management without running the server."""

    def test_send_log_buffers_entries(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge.send_log("test message", "orchestrator", None)
        assert len(bridge._log_buffer) == 1
        entry = bridge._log_buffer[0]
        assert entry["type"] == "log"
        assert entry["data"]["message"] == "test message"
        assert entry["data"]["target"] == "orchestrator"

    def test_send_log_trims_buffer(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge._max_log_buffer = 5
        for i in range(10):
            bridge.send_log(f"msg {i}", "orchestrator")
        assert len(bridge._log_buffer) == 5
        # Should keep the last 5
        assert bridge._log_buffer[0]["data"]["message"] == "msg 5"

    def test_send_work_item_stores_state(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge.send_work_item("item-1", "Fix bug", "in_progress")
        assert bridge._current_work_item == {
            "item_id": "item-1",
            "title": "Fix bug",
            "status": "in_progress",
        }

    def test_send_agent_name_stores_state(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge.send_agent_name("pokepoke_agent_42")
        assert bridge._current_agent_name == "pokepoke_agent_42"

    def test_send_stats_stores_state(self):
        from pokepoke.desktop_bridge import DesktopBridge
        from pokepoke.types import SessionStats, AgentStats
        bridge = DesktopBridge()
        stats = SessionStats(
            agent_stats=AgentStats(input_tokens=1000, output_tokens=500),
            items_completed=3,
            work_agent_runs=2,
        )
        bridge.send_stats(stats, 120.5)
        assert bridge._current_stats is not None
        assert bridge._current_stats["elapsed_time"] == 120.5
        assert bridge._current_stats["items_completed"] == 3
        assert bridge._current_stats["agent_stats"]["input_tokens"] == 1000

    def test_send_stats_none(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge.send_stats(None, 60.0)
        assert bridge._current_stats is not None
        assert bridge._current_stats["elapsed_time"] == 60.0

    def test_clear_logs(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge.send_log("msg 1", "orchestrator")
        bridge.send_log("msg 2", "agent")
        assert len(bridge._log_buffer) == 2
        bridge.clear_logs()
        assert len(bridge._log_buffer) == 0

    def test_send_progress(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        # Should not raise even without clients
        bridge.send_progress(True, "Working...")

    def test_broadcast_no_clients_is_noop(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        # No loop, no clients — should be a silent no-op
        bridge._broadcast({"type": "test", "data": {}})


class TestDesktopBridgeLifecycle:
    """Test start/stop lifecycle without starting real servers."""

    def test_start_sets_running(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge(port=19160)
        # Mock _run_server so we don't actually start a real server
        bridge._run_server = lambda: None  # type: ignore
        bridge.start()
        try:
            assert bridge.is_running is True
            assert bridge._thread is not None
        finally:
            bridge._running = False

    def test_stop_clears_running(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge(port=19161)
        bridge._run_server = lambda: None  # type: ignore
        bridge.start()
        bridge.stop()
        assert bridge.is_running is False

    def test_double_start_is_safe(self):
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge(port=19162)
        bridge._run_server = lambda: None  # type: ignore
        bridge.start()
        try:
            thread1 = bridge._thread
            bridge.start()  # Should be a no-op
            assert bridge._thread is thread1
        finally:
            bridge._running = False


class TestDesktopBridgeAsync:
    """Test async server methods directly."""

    def test_handle_client_message_ping(self):
        """Test that ping messages get pong responses."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        mock_ws = AsyncMock()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                bridge._handle_client_message(mock_ws, {"type": "ping"})
            )
            mock_ws.send.assert_called_once()
            sent = json.loads(mock_ws.send.call_args[0][0])
            assert sent["type"] == "pong"
            assert "timestamp" in sent["data"]
        finally:
            loop.close()

    def test_handle_client_message_unknown(self):
        """Unknown message types should be silently ignored."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        mock_ws = AsyncMock()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                bridge._handle_client_message(mock_ws, {"type": "unknown"})
            )
            mock_ws.send.assert_not_called()
        finally:
            loop.close()

    def test_send_state_snapshot_empty(self):
        """Snapshot to new client with no state sends just connected."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        mock_ws = AsyncMock()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bridge._send_state_snapshot(mock_ws))
            # Should have sent at least the connected message
            assert mock_ws.send.call_count >= 1
            first_msg = json.loads(mock_ws.send.call_args_list[0][0][0])
            assert first_msg["type"] == "connected"
        finally:
            loop.close()

    def test_send_state_snapshot_full(self):
        """Snapshot with all state populated sends everything."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge.send_log("test log", "orchestrator")
        bridge.send_work_item("item-1", "Fix it", "working")
        bridge.send_agent_name("agent_42")
        bridge._current_stats = {"elapsed_time": 10.0}

        mock_ws = AsyncMock()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bridge._send_state_snapshot(mock_ws))
            # connected + 1 log + work_item + agent_name + stats = 5 calls
            assert mock_ws.send.call_count == 5
            types = [
                json.loads(call[0][0])["type"]
                for call in mock_ws.send.call_args_list
            ]
            assert "connected" in types
            assert "log" in types
            assert "work_item" in types
            assert "agent_name" in types
            assert "stats" in types
        finally:
            loop.close()

    def test_broadcast_async_handles_disconnected(self):
        """Broadcast removes clients that throw exceptions."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        good_client = AsyncMock()
        bad_client = AsyncMock()
        bad_client.send.side_effect = ConnectionError("gone")
        bridge._clients = {good_client, bad_client}

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                bridge._broadcast_async('{"type":"test","data":{}}')
            )
            # Bad client should be removed
            assert bad_client not in bridge._clients
            assert good_client in bridge._clients
        finally:
            loop.close()

    def test_broadcast_async_empty_clients(self):
        """Broadcast with no clients is a no-op."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        bridge._clients = set()
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                bridge._broadcast_async('{"type":"test","data":{}}')
            )
        finally:
            loop.close()

    def test_run_server_creates_loop(self):
        """_run_server should create an event loop."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge(port=19170)
        # Patch _serve to immediately stop
        async def fake_serve():
            bridge._running = False
        bridge._serve = fake_serve  # type: ignore
        bridge._running = True
        bridge._run_server()
        # After running, the loop should have been created and closed
        assert bridge._loop is not None

    def test_handle_client_sends_snapshot_and_listens(self):
        """_handle_client sends snapshot then listens for messages."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()
        
        # Create a mock websocket that yields one message then stops
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: self
        messages = [json.dumps({"type": "ping"})]
        
        async def async_iter():
            for msg in messages:
                yield msg
        
        mock_ws.__aiter__ = lambda s: async_iter()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bridge._handle_client(mock_ws))
            # Client should have been added and then removed
            assert mock_ws not in bridge._clients
        finally:
            loop.close()

    def test_handle_client_bad_json(self):
        """Client sending bad JSON should not crash."""
        from pokepoke.desktop_bridge import DesktopBridge
        bridge = DesktopBridge()

        mock_ws = AsyncMock()
        async def async_iter():
            yield "not valid json {"
        mock_ws.__aiter__ = lambda s: async_iter()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(bridge._handle_client(mock_ws))
        finally:
            loop.close()
