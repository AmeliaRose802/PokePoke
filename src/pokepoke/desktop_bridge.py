"""WebSocket bridge for PokePoke desktop app.

Provides a WebSocket server that streams orchestrator events to the
desktop frontend (Tauri/React). This is the communication layer between
the Python orchestrator and the desktop UI.

Protocol:
    All messages are JSON with a "type" field and a "data" payload.
    Server → Client: log, work_item, stats, agent_name, progress, connected
    Client → Server: command messages (future: start/stop agents, config)

Requires: websockets>=12.0
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import asdict
from typing import Optional, Any, Set, TYPE_CHECKING

try:
    import websockets
    from websockets.asyncio.server import serve, ServerConnection
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

if TYPE_CHECKING:
    from pokepoke.types import SessionStats

# Default WebSocket port
DEFAULT_WS_PORT = 9160


class DesktopBridge:
    """WebSocket server that bridges orchestrator events to the desktop app.

    Runs in a background thread with its own asyncio event loop.
    Thread-safe: all public methods can be called from any thread.
    """

    def __init__(self, port: int = DEFAULT_WS_PORT) -> None:
        if not HAS_WEBSOCKETS:
            raise ImportError(
                "websockets package required for desktop bridge. "
                "Install with: pip install websockets>=12.0"
            )
        self._port = port
        self._clients: Set[Any] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._server: Optional[Any] = None
        self._running = False
        self._lock = threading.Lock()

        # State snapshot for new client connections
        self._current_work_item: Optional[dict[str, str]] = None
        self._current_stats: Optional[dict[str, Any]] = None
        self._current_agent_name: str = ""
        self._log_buffer: list[dict[str, Any]] = []
        self._max_log_buffer = 500  # Keep last N log entries for new clients

    def start(self) -> None:
        """Start the WebSocket server in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="desktop-bridge",
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the WebSocket server."""
        self._running = False
        if self._loop and self._server:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def is_running(self) -> bool:
        """Check if the bridge is running."""
        return self._running

    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        return len(self._clients)

    def _run_server(self) -> None:
        """Run the asyncio event loop for the WebSocket server."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception:
            pass
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        """Start the WebSocket server and run until stopped."""
        async with serve(self._handle_client, "127.0.0.1", self._port) as server:
            self._server = server
            # Wait until stopped
            while self._running:
                await asyncio.sleep(0.1)

    async def _handle_client(self, websocket: ServerConnection) -> None:
        """Handle a new WebSocket client connection."""
        self._clients.add(websocket)
        try:
            # Send current state snapshot to the new client
            await self._send_state_snapshot(websocket)

            # Listen for client commands (future use)
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_client_message(websocket, data)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass
        finally:
            self._clients.discard(websocket)

    async def _send_state_snapshot(self, websocket: ServerConnection) -> None:
        """Send current state to a newly connected client."""
        # Send connection confirmation
        await websocket.send(json.dumps({
            "type": "connected",
            "data": {"port": self._port, "timestamp": time.time()}
        }))

        # Send buffered logs
        for log_entry in self._log_buffer:
            await websocket.send(json.dumps(log_entry))

        # Send current work item
        if self._current_work_item:
            await websocket.send(json.dumps({
                "type": "work_item",
                "data": self._current_work_item,
            }))

        # Send current agent name
        if self._current_agent_name:
            await websocket.send(json.dumps({
                "type": "agent_name",
                "data": {"name": self._current_agent_name},
            }))

        # Send current stats
        if self._current_stats:
            await websocket.send(json.dumps({
                "type": "stats",
                "data": self._current_stats,
            }))

    async def _handle_client_message(
        self, websocket: ServerConnection, data: dict[str, Any]
    ) -> None:
        """Handle an incoming message from a client.

        Future: start/stop agents, change config, etc.
        """
        msg_type = data.get("type", "")
        if msg_type == "ping":
            await websocket.send(json.dumps({
                "type": "pong",
                "data": {"timestamp": time.time()}
            }))

    def _broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to all connected clients (thread-safe)."""
        if not self._clients or not self._loop:
            return

        msg_str = json.dumps(message)
        # Schedule the broadcast on the event loop
        self._loop.call_soon_threadsafe(
            asyncio.ensure_future,
            self._broadcast_async(msg_str),
        )

    async def _broadcast_async(self, msg_str: str) -> None:
        """Broadcast a message to all connected clients."""
        if not self._clients:
            return
        # Send to all clients, ignore failures
        disconnected = set()
        for client in self._clients.copy():
            try:
                await client.send(msg_str)
            except Exception:
                disconnected.add(client)
        self._clients -= disconnected

    # ─── Public API (thread-safe) ─────────────────────────────────────

    def send_log(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:
        """Send a log message to all connected desktop clients."""
        entry = {
            "type": "log",
            "data": {
                "message": message,
                "target": target,
                "style": style,
                "timestamp": time.time(),
            },
        }
        with self._lock:
            self._log_buffer.append(entry)
            # Trim buffer to max size
            if len(self._log_buffer) > self._max_log_buffer:
                self._log_buffer = self._log_buffer[-self._max_log_buffer:]
        self._broadcast(entry)

    def send_work_item(self, item_id: str, title: str, status: str = "") -> None:
        """Send work item update to all connected desktop clients."""
        data = {"item_id": item_id, "title": title, "status": status}
        with self._lock:
            self._current_work_item = data
        self._broadcast({"type": "work_item", "data": data})

    def send_stats(
        self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0
    ) -> None:
        """Send stats update to all connected desktop clients."""
        stats_data: dict[str, Any] = {"elapsed_time": elapsed_time}
        if session_stats:
            stats_data["agent_stats"] = asdict(session_stats.agent_stats)
            stats_data["items_completed"] = session_stats.items_completed
            stats_data["work_agent_runs"] = session_stats.work_agent_runs
            stats_data["gate_agent_runs"] = session_stats.gate_agent_runs
            stats_data["tech_debt_agent_runs"] = session_stats.tech_debt_agent_runs
            stats_data["janitor_agent_runs"] = session_stats.janitor_agent_runs
            stats_data["backlog_cleanup_agent_runs"] = session_stats.backlog_cleanup_agent_runs
            stats_data["cleanup_agent_runs"] = session_stats.cleanup_agent_runs
            stats_data["beta_tester_agent_runs"] = session_stats.beta_tester_agent_runs
            stats_data["code_review_agent_runs"] = session_stats.code_review_agent_runs
            stats_data["worktree_cleanup_agent_runs"] = session_stats.worktree_cleanup_agent_runs
        with self._lock:
            self._current_stats = stats_data
        self._broadcast({"type": "stats", "data": stats_data})

    def send_agent_name(self, name: str) -> None:
        """Send agent name update to all connected desktop clients."""
        with self._lock:
            self._current_agent_name = name
        self._broadcast({"type": "agent_name", "data": {"name": name}})

    def send_progress(self, active: bool, status: str = "") -> None:
        """Send progress indicator update to all connected desktop clients."""
        self._broadcast({
            "type": "progress",
            "data": {"active": active, "status": status},
        })

    def clear_logs(self) -> None:
        """Clear the log buffer."""
        with self._lock:
            self._log_buffer.clear()
