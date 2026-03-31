"""Tests for periodic process tree snapshot diagnostics in SDKWatchdog."""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pokepoke.models.sdk_watchdog import SDKWatchdog
from pokepoke.models.sdk_watchdog_diagnostics import (
    periodic_diagnostics_loop,
    resolve_diagnostics_log_path,
)


class TestBackwardCompatAliases:
    def test_check_tool_watchdog_alias(self):
        from pokepoke.models.sdk_watchdog import _check_tool_watchdog
        assert _check_tool_watchdog is SDKWatchdog.check_tool_watchdog

    def test_await_completion_alias(self):
        from pokepoke.models.sdk_watchdog import _await_completion
        assert _await_completion is SDKWatchdog.await_completion


class TestResolveDiagnosticsLogPath:
    def test_returns_path_when_handler_has_item_logger(self, tmp_path):
        run_dir = tmp_path / "run_123"
        items_dir = run_dir / "items"
        items_dir.mkdir(parents=True)
        log_file = items_dir / "item-1.log"
        log_file.touch()

        handler = MagicMock()
        handler._item_logger.log_path = log_file
        result = resolve_diagnostics_log_path(handler)
        assert result == run_dir / "tool_diagnostics.log"

    def test_returns_none_when_no_handler(self):
        assert resolve_diagnostics_log_path(None) is None

    def test_returns_none_when_no_item_logger(self):
        handler = MagicMock()
        handler._item_logger = None
        assert resolve_diagnostics_log_path(handler) is None

    def test_returns_none_when_no_log_path(self):
        handler = MagicMock()
        handler._item_logger = MagicMock(spec=[])
        assert resolve_diagnostics_log_path(handler) is None


class TestPeriodicDiagnosticsLoop:
    @pytest.mark.asyncio
    async def test_skips_when_no_active_tools(self, tmp_path):
        """Loop should not write anything when tool_start_times is empty."""
        diag_log = tmp_path / "tool_diagnostics.log"
        stop = asyncio.Event()
        stats = {"tool_start_times": {}}

        # Set stop after a very short time
        async def _stop_soon():
            await asyncio.sleep(0.05)
            stop.set()

        task = asyncio.create_task(
            periodic_diagnostics_loop(stats, None, diag_log, stop)
        )
        stopper = asyncio.create_task(_stop_soon())
        await asyncio.gather(task, stopper)

        assert not diag_log.exists()

    @pytest.mark.asyncio
    async def test_writes_snapshot_for_active_tool(self, tmp_path):
        """Loop should write diagnostic entries for active tool calls."""
        diag_log = tmp_path / "tool_diagnostics.log"
        stop = asyncio.Event()
        stats = {"tool_start_times": {"t1": time.monotonic() - 120}}
        handler = MagicMock()
        handler._pending_tools = {
            "t1": {"name": "powershell", "args": {"command": "git status"}}
        }
        handler._item_logger = None

        with patch(
            "pokepoke.models.sdk_watchdog_diagnostics._log_process_tree_snapshot"
        ) as mock_snapshot, patch(
            "pokepoke.models.sdk_watchdog_diagnostics._SNAPSHOT_INTERVAL", 0.01
        ):
            async def _stop_soon():
                await asyncio.sleep(0.05)
                stop.set()

            task = asyncio.create_task(
                periodic_diagnostics_loop(
                    stats, handler, diag_log, stop
                )
            )
            stopper = asyncio.create_task(_stop_soon())
            await asyncio.gather(task, stopper)

        mock_snapshot.assert_called()
        call_args = mock_snapshot.call_args
        assert call_args[0][0] == "powershell"

        assert diag_log.exists()
        content = diag_log.read_text(encoding="utf-8")
        assert "tool=powershell" in content
        assert "tool_id=t1" in content
        assert "git status" in content

    @pytest.mark.asyncio
    async def test_stops_on_event(self):
        """Loop should exit promptly when stop event is set."""
        stop = asyncio.Event()
        stats = {"tool_start_times": {"t1": time.monotonic()}}
        stop.set()

        with patch("pokepoke.models.sdk_watchdog_diagnostics._log_process_tree_snapshot"):
            # Should return immediately since stop is already set
            await asyncio.wait_for(
                periodic_diagnostics_loop(
                    stats, None, Path("unused"), stop
                ),
                timeout=2.0,
            )

    @pytest.mark.asyncio
    async def test_handles_file_write_error(self, tmp_path):
        """Loop should not crash if diagnostics log write fails."""
        # Use a path that can't be written (directory as file)
        bad_path = tmp_path / "nested" / "deep" / "tool_diagnostics.log"
        # Don't create parent directories

        stop = asyncio.Event()
        stats = {"tool_start_times": {"t1": time.monotonic() - 60}}

        with patch(
            "pokepoke.models.sdk_watchdog_diagnostics._log_process_tree_snapshot"
        ), patch(
            "pokepoke.models.sdk_watchdog_diagnostics._SNAPSHOT_INTERVAL", 0.01
        ):
            async def _stop_soon():
                await asyncio.sleep(0.05)
                stop.set()

            task = asyncio.create_task(
                periodic_diagnostics_loop(
                    stats, None, bad_path, stop
                )
            )
            stopper = asyncio.create_task(_stop_soon())
            # Should not raise
            await asyncio.gather(task, stopper)

    @pytest.mark.asyncio
    async def test_multiple_active_tools(self, tmp_path):
        """Loop should snapshot all active tools."""
        diag_log = tmp_path / "tool_diagnostics.log"
        stop = asyncio.Event()
        stats = {
            "tool_start_times": {
                "t1": time.monotonic() - 200,
                "t2": time.monotonic() - 100,
            }
        }
        handler = MagicMock()
        handler._pending_tools = {
            "t1": {"name": "powershell", "args": {"command": "npm test"}},
            "t2": {"name": "edit_file", "args": {"path": "foo.py"}},
        }
        handler._item_logger = None

        with patch(
            "pokepoke.models.sdk_watchdog_diagnostics._log_process_tree_snapshot"
        ) as mock_snap, patch(
            "pokepoke.models.sdk_watchdog_diagnostics._SNAPSHOT_INTERVAL", 0.01
        ):
            async def _stop_soon():
                await asyncio.sleep(0.05)
                stop.set()

            task = asyncio.create_task(
                periodic_diagnostics_loop(
                    stats, handler, diag_log, stop
                )
            )
            stopper = asyncio.create_task(_stop_soon())
            await asyncio.gather(task, stopper)

        # Should have been called for both tools (at least once each)
        assert mock_snap.call_count >= 2
        content = diag_log.read_text(encoding="utf-8")
        assert "powershell" in content
        assert "edit_file" in content


class TestAwaitCompletionDiagnosticsIntegration:
    @pytest.mark.asyncio
    async def test_starts_and_stops_diagnostics_task(self, tmp_path):
        """await_completion should start the diagnostics task and clean up."""
        run_dir = tmp_path / "run_abc"
        items_dir = run_dir / "items"
        items_dir.mkdir(parents=True)
        log_file = items_dir / "item-1.log"
        log_file.touch()

        handler = MagicMock()
        handler._item_logger.log_path = log_file
        handler._pending_tools = {}

        session = AsyncMock()
        client = AsyncMock()
        client.ping = AsyncMock()
        done = asyncio.Event()
        done.set()  # Complete immediately

        stats = {
            "tool_start_times": {},
            "event_count": 0,
            "last_event_time": time.monotonic(),
            "pending_tool_calls": 0,
            "turn_count": 0,
            "last_tool_activity_time": 0,
        }

        with patch(
            "pokepoke.models.sdk_watchdog.is_shutting_down", return_value=False
        ), patch(
            "pokepoke.models.sdk_watchdog_diagnostics._log_process_tree_snapshot"
        ):
            result = await SDKWatchdog.await_completion(
                session, client, done, max_timeout=10.0,
                stats=stats, handler=handler,
            )

        assert result is None  # Normal completion

    @pytest.mark.asyncio
    async def test_no_diagnostics_without_stats(self):
        """No diagnostics task should be created when stats is None."""
        session = AsyncMock()
        client = AsyncMock()
        done = asyncio.Event()
        done.set()

        with patch(
            "pokepoke.models.sdk_watchdog.is_shutting_down", return_value=False
        ):
            result = await SDKWatchdog.await_completion(
                session, client, done, max_timeout=10.0,
                stats=None,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_diagnostics_without_handler(self):
        """No diagnostics task when handler doesn't have item logger."""
        session = AsyncMock()
        client = AsyncMock()
        done = asyncio.Event()
        done.set()

        stats = {
            "tool_start_times": {},
            "event_count": 0,
            "last_event_time": time.monotonic(),
            "pending_tool_calls": 0,
            "turn_count": 0,
            "last_tool_activity_time": 0,
        }

        with patch(
            "pokepoke.models.sdk_watchdog.is_shutting_down", return_value=False
        ):
            result = await SDKWatchdog.await_completion(
                session, client, done, max_timeout=10.0,
                stats=stats, handler=None,
            )

        assert result is None


# ── SDKWatchdog static helper coverage ───────────────────────────────────────


class TestCheckClientState:
    def test_sets_done_on_disconnected(self):
        client = MagicMock()
        client.get_state.return_value = "disconnected"
        done = asyncio.Event()
        SDKWatchdog._check_client_state(client, done)
        assert done.is_set()

    def test_sets_done_on_error(self):
        client = MagicMock()
        client.get_state.return_value = "error"
        done = asyncio.Event()
        SDKWatchdog._check_client_state(client, done)
        assert done.is_set()

    def test_no_op_on_connected(self):
        client = MagicMock()
        client.get_state.return_value = "connected"
        done = asyncio.Event()
        SDKWatchdog._check_client_state(client, done)
        assert not done.is_set()

    def test_handles_exception(self):
        client = MagicMock()
        client.get_state.side_effect = RuntimeError("boom")
        done = asyncio.Event()
        SDKWatchdog._check_client_state(client, done)
        assert not done.is_set()


class TestLogEventGap:
    def test_returns_now_when_interval_elapsed(self):
        stats = {
            "last_event_time": time.monotonic() - 120,
            "pending_tool_calls": 0,
            "event_count": 5,
            "turn_count": 1,
        }
        old_log_time = time.monotonic() - 40  # >30s ago
        result = SDKWatchdog._log_event_gap(stats, old_log_time)
        assert result > old_log_time

    def test_returns_same_when_interval_not_elapsed(self):
        stats = {
            "last_event_time": time.monotonic(),
            "pending_tool_calls": 0,
            "event_count": 5,
            "turn_count": 1,
        }
        recent_log_time = time.monotonic()
        result = SDKWatchdog._log_event_gap(stats, recent_log_time)
        assert result == recent_log_time


class TestCheckProcessLiveness:
    @pytest.mark.asyncio
    async def test_aborts_on_ping_failures_exceeding_threshold(self):
        session = AsyncMock()
        stats = {
            "turn_count": 0,
            "pending_tool_calls": 1,
            "event_count": 5,
        }
        done = asyncio.Event()
        should_abort, reason, _ = await SDKWatchdog._check_process_liveness(
            client=MagicMock(spec=[]),
            stats=stats,
            consecutive_ping_failures=5,
            max_ping_failures=3,
            process_output_timeout=300,
            gap=10,
            ping_ok=False,
            session=session,
            done=done,
        )
        assert should_abort
        assert "PROCESS DEAD" in reason
        session.abort.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_treats_as_completion_when_work_done_and_exited_ok(self):
        session = AsyncMock()
        proc = MagicMock()
        proc.returncode = 0
        client = MagicMock()
        client._process = proc
        stats = {
            "turn_count": 3,
            "pending_tool_calls": 0,
            "event_count": 10,
        }
        done = asyncio.Event()
        should_abort, _, _ = await SDKWatchdog._check_process_liveness(
            client=client,
            stats=stats,
            consecutive_ping_failures=5,
            max_ping_failures=3,
            process_output_timeout=300,
            gap=10,
            ping_ok=False,
            session=session,
            done=done,
        )
        assert not should_abort
        assert done.is_set()

    @pytest.mark.asyncio
    async def test_aborts_on_unresponsive(self):
        session = AsyncMock()
        stats = {
            "turn_count": 1,
            "pending_tool_calls": 0,
            "event_count": 5,
        }
        done = asyncio.Event()
        should_abort, reason, _ = await SDKWatchdog._check_process_liveness(
            client=MagicMock(spec=[]),
            stats=stats,
            consecutive_ping_failures=1,
            max_ping_failures=3,
            process_output_timeout=300,
            gap=500,
            ping_ok=False,
            session=session,
            done=done,
        )
        assert should_abort
        assert "PROCESS UNRESPONSIVE" in reason

    @pytest.mark.asyncio
    async def test_no_abort_when_healthy(self):
        session = AsyncMock()
        stats = {
            "turn_count": 1,
            "pending_tool_calls": 0,
            "event_count": 5,
        }
        done = asyncio.Event()
        should_abort, reason, _ = await SDKWatchdog._check_process_liveness(
            client=MagicMock(spec=[]),
            stats=stats,
            consecutive_ping_failures=0,
            max_ping_failures=3,
            process_output_timeout=300,
            gap=10,
            ping_ok=True,
            session=session,
            done=done,
        )
        assert not should_abort
        assert reason == ""


class TestCheckInactivity:
    @pytest.mark.asyncio
    async def test_returns_false_when_timeout_zero(self):
        stats = {"last_event_time": time.monotonic(), "pending_tool_calls": 0,
                 "last_tool_activity_time": 0}
        result = await SDKWatchdog._check_inactivity(stats, 0, AsyncMock())
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_pending_tools(self):
        stats = {"last_event_time": time.monotonic() - 1000, "pending_tool_calls": 1,
                 "last_tool_activity_time": 0}
        with patch.object(SDKWatchdog, "_get_effective_activity_time",
                          return_value=(time.monotonic() - 1000, False, None)):
            result = await SDKWatchdog._check_inactivity(stats, 600, AsyncMock())
        assert result is False

    @pytest.mark.asyncio
    async def test_aborts_on_inactivity(self):
        session = AsyncMock()
        stats = {"last_event_time": time.monotonic() - 1000,
                 "pending_tool_calls": 0,
                 "last_tool_activity_time": time.monotonic() - 200,
                 "event_count": 5}
        with patch.object(SDKWatchdog, "_get_effective_activity_time",
                          return_value=(time.monotonic() - 1000, False, None)):
            result = await SDKWatchdog._check_inactivity(stats, 600, session)
        assert result is True
        session.abort.assert_awaited_once()


class TestGetEffectiveActivityTime:
    def test_returns_last_event_time_without_children(self):
        now = time.monotonic()
        stats = {"last_event_time": now}
        with patch("pokepoke.models.sdk_watchdog.terminal_ui") as mock_ui:
            mock_ui.ui.has_active_child_agents.return_value = False
            with patch("pokepoke.desktop.thread_output_router._thread_output") as mock_thread:
                mock_thread.agent_id = "agent-1"
                effective, has_children, _ = SDKWatchdog._get_effective_activity_time(stats)
        assert effective == now
        assert not has_children

    def test_uses_child_activity_when_active(self):
        now = time.monotonic()
        child_time_val = now + 10
        stats = {"last_event_time": now}
        with patch("pokepoke.models.sdk_watchdog.terminal_ui") as mock_ui:
            mock_ui.ui.has_active_child_agents.return_value = True
            mock_ui.ui.get_child_agent_activity_time.return_value = child_time_val
            with patch("pokepoke.desktop.thread_output_router._thread_output") as mock_thread:
                mock_thread.agent_id = "agent-1"
                effective, has_children, _ = SDKWatchdog._get_effective_activity_time(stats)
        assert has_children
        assert effective == child_time_val


class TestPollLoopShutdown:
    @pytest.mark.asyncio
    async def test_returns_shutdown_on_shutdown_signal(self):
        session = AsyncMock()
        client = AsyncMock()
        done = asyncio.Event()
        stats = {
            "tool_start_times": {},
            "event_count": 0,
            "last_event_time": time.monotonic(),
            "pending_tool_calls": 0,
            "turn_count": 0,
            "last_tool_activity_time": 0,
        }
        with patch("pokepoke.models.sdk_watchdog.is_shutting_down", return_value=True):
            result = await SDKWatchdog._poll_loop(
                session, client, done,
                deadline=asyncio.get_event_loop().time() + 100,
                max_timeout=100,
                stats=stats,
                inactivity_timeout=600,
                tool_call_timeout=600,
                handler=None,
                process_output_timeout=300,
                max_ping_failures=3,
                last_hb=time.monotonic(),
                last_hb_events=0,
                consecutive_ping_failures=0,
                last_event_gap_log=time.monotonic(),
            )
        assert result == "shutdown"

    @pytest.mark.asyncio
    async def test_returns_timeout_when_deadline_passed(self):
        session = AsyncMock()
        client = AsyncMock()
        client.get_state.return_value = "connected"
        done = asyncio.Event()
        stats = {
            "tool_start_times": {},
            "event_count": 0,
            "last_event_time": time.monotonic(),
            "pending_tool_calls": 0,
            "turn_count": 0,
            "last_tool_activity_time": 0,
        }
        with patch("pokepoke.models.sdk_watchdog.is_shutting_down", return_value=False):
            result = await SDKWatchdog._poll_loop(
                session, client, done,
                deadline=asyncio.get_event_loop().time() - 1,  # already past
                max_timeout=10,
                stats=stats,
                inactivity_timeout=600,
                tool_call_timeout=600,
                handler=None,
                process_output_timeout=300,
                max_ping_failures=3,
                last_hb=time.monotonic(),
                last_hb_events=0,
                consecutive_ping_failures=0,
                last_event_gap_log=time.monotonic(),
            )
        assert result == "timeout"


class TestPollLoopHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_runs_ping_and_completes(self):
        """Exercise the heartbeat path: last_hb is old so the heartbeat fires,
        ping succeeds, then done is set to exit."""
        session = AsyncMock()
        client = AsyncMock()
        client.get_state.return_value = "connected"
        client.ping = AsyncMock()  # ping succeeds

        done = asyncio.Event()
        now = time.monotonic()
        stats = {
            "tool_start_times": {},
            "event_count": 5,
            "last_event_time": now,
            "pending_tool_calls": 0,
            "turn_count": 1,
            "last_tool_activity_time": now,
        }

        call_count = 0
        orig_shutting_down = False

        def _shutdown_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                done.set()
            return orig_shutting_down

        with patch("pokepoke.models.sdk_watchdog.is_shutting_down",
                    side_effect=_shutdown_side_effect):
            result = await SDKWatchdog._poll_loop(
                session, client, done,
                deadline=asyncio.get_event_loop().time() + 100,
                max_timeout=100,
                stats=stats,
                inactivity_timeout=600,
                tool_call_timeout=600,
                handler=None,
                process_output_timeout=300,
                max_ping_failures=3,
                last_hb=now - 60,  # old enough to trigger heartbeat
                last_hb_events=0,
                consecutive_ping_failures=0,
                last_event_gap_log=now,
            )
        assert result is None  # normal completion
        client.ping.assert_awaited()

    @pytest.mark.asyncio
    async def test_heartbeat_ping_failure_increments_counter(self):
        """Ping failure increments consecutive_ping_failures, then done exits."""
        session = AsyncMock()
        client = AsyncMock()
        client.get_state.return_value = "connected"
        client.ping = AsyncMock(side_effect=ConnectionError("no response"))

        done = asyncio.Event()
        now = time.monotonic()
        stats = {
            "tool_start_times": {},
            "event_count": 5,
            "last_event_time": now,
            "pending_tool_calls": 0,
            "turn_count": 1,
            "last_tool_activity_time": now,
        }

        call_count = 0

        def _shutdown_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                done.set()
            return False

        with patch("pokepoke.models.sdk_watchdog.is_shutting_down",
                    side_effect=_shutdown_side_effect):
            result = await SDKWatchdog._poll_loop(
                session, client, done,
                deadline=asyncio.get_event_loop().time() + 100,
                max_timeout=100,
                stats=stats,
                inactivity_timeout=600,
                tool_call_timeout=600,
                handler=None,
                process_output_timeout=300,
                max_ping_failures=10,  # high so we don't abort
                last_hb=now - 60,
                last_hb_events=0,
                consecutive_ping_failures=0,
                last_event_gap_log=now,
            )
        assert result is None  # completed via done event
        client.ping.assert_awaited()

    @pytest.mark.asyncio
    async def test_heartbeat_process_dead_returns(self):
        """When ping failures exceed threshold, returns process_dead."""
        session = AsyncMock()
        client = AsyncMock()
        client.get_state.return_value = "connected"
        client.ping = AsyncMock(side_effect=ConnectionError("dead"))

        done = asyncio.Event()
        now = time.monotonic()
        stats = {
            "tool_start_times": {},
            "event_count": 5,
            "last_event_time": now,
            "pending_tool_calls": 0,
            "turn_count": 0,
            "last_tool_activity_time": now,
        }

        with patch("pokepoke.models.sdk_watchdog.is_shutting_down", return_value=False):
            result = await SDKWatchdog._poll_loop(
                session, client, done,
                deadline=asyncio.get_event_loop().time() + 100,
                max_timeout=100,
                stats=stats,
                inactivity_timeout=600,
                tool_call_timeout=600,
                handler=None,
                process_output_timeout=300,
                max_ping_failures=3,
                last_hb=now - 60,
                last_hb_events=0,
                consecutive_ping_failures=5,  # already exceeds threshold
                last_event_gap_log=now,
            )
        assert result == "process_dead"

    @pytest.mark.asyncio
    async def test_heartbeat_ping_fail_with_pending_tools_ignores(self):
        """Ping failure while tools pending & proc alive should be ignored."""
        session = AsyncMock()
        proc = MagicMock()
        proc.returncode = None  # Process still alive
        client = AsyncMock()
        client.get_state.return_value = "connected"
        client.ping = AsyncMock(side_effect=ConnectionError("blocked"))
        client._process = proc

        done = asyncio.Event()
        now = time.monotonic()
        stats = {
            "tool_start_times": {},
            "event_count": 5,
            "last_event_time": now,
            "pending_tool_calls": 2,  # tools pending
            "turn_count": 1,
            "last_tool_activity_time": now,
        }

        # After the heartbeat fires, set done to exit the loop
        async def _ping_then_done():
            done.set()
            raise ConnectionError("blocked")

        client.ping = AsyncMock(side_effect=_ping_then_done)

        with patch("pokepoke.models.sdk_watchdog.is_shutting_down", return_value=False):
            result = await SDKWatchdog._poll_loop(
                session, client, done,
                deadline=asyncio.get_event_loop().time() + 100,
                max_timeout=100,
                stats=stats,
                inactivity_timeout=600,
                tool_call_timeout=600,
                handler=None,
                process_output_timeout=300,
                max_ping_failures=3,
                last_hb=now - 60,
                last_hb_events=0,
                consecutive_ping_failures=0,
                last_event_gap_log=now,
            )
        assert result is None  # normal completion, not process_dead

    @pytest.mark.asyncio
    async def test_client_disconnect_sets_done(self):
        """If client.get_state returns 'disconnected', done should be set."""
        done = asyncio.Event()
        client = MagicMock()
        client.get_state.return_value = "disconnected"
        SDKWatchdog._check_client_state(client, done)
        assert done.is_set()


