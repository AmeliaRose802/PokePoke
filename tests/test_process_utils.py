"""Tests for process_utils module."""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
import subprocess

import pytest

import pokepoke.process_utils as process_utils_mod
from pokepoke.process_utils import (
    check_copilot_processes,
    wait_for_process_cleanup,
    shutdown_copilot_client,
)


@pytest.fixture(autouse=True)
def reset_copilot_cache():
    """Reset the module-level cache before each test to prevent cross-test pollution."""
    process_utils_mod._copilot_process_cache = None
    yield
    process_utils_mod._copilot_process_cache = None


class TestCheckCopilotProcesses:
    """Tests for check_copilot_processes."""

    @patch('pokepoke.process_utils.os')
    def test_returns_zero_on_non_windows(self, mock_os):
        mock_os.name = 'posix'
        assert check_copilot_processes() == 0

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_returns_process_count_on_windows(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(
            stdout='"Image Name","PID"\n"copilot.exe","1234"\n"copilot.exe","5678"'
        )
        assert check_copilot_processes() == 2

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_returns_zero_when_no_processes(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        assert check_copilot_processes() == 0

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_returns_zero_on_exception(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='tasklist', timeout=30)
        assert check_copilot_processes() == 0

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_uses_utf8_encoding(self, mock_run, mock_os):
        """tasklist is called with UTF-8 encoding to avoid UnicodeDecodeError."""
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        check_copilot_processes()
        _, kwargs = mock_run.call_args
        assert kwargs.get('encoding') == 'utf-8'
        assert kwargs.get('errors') == 'replace'

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_uses_30s_timeout(self, mock_run, mock_os):
        """tasklist timeout is 30 seconds (increased from 5s)."""
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        check_copilot_processes()
        _, kwargs = mock_run.call_args
        assert kwargs.get('timeout') == 30

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_caches_result_within_ttl(self, mock_run, mock_os):
        """Repeated calls within the TTL window reuse the cached result."""
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='"Image Name","PID"\n"copilot.exe","1234"')
        result1 = check_copilot_processes()
        result2 = check_copilot_processes()
        assert result1 == 1
        assert result2 == 1
        # subprocess.run should only be called once due to caching
        assert mock_run.call_count == 1

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    @patch('pokepoke.process_utils.time')
    def test_refreshes_cache_after_ttl(self, mock_time, mock_run, mock_os):
        """After TTL expires, a fresh tasklist call is made."""
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        # First call at t=0
        mock_time.time.return_value = 0.0
        check_copilot_processes()
        # Second call after TTL
        mock_time.time.return_value = process_utils_mod._COPILOT_CACHE_TTL + 1.0
        check_copilot_processes()
        assert mock_run.call_count == 2

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_does_not_cache_exception_result(self, mock_run, mock_os):
        """Transient tasklist failures must not be cached as 0 (would mask running processes)."""
        mock_os.name = 'nt'
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd='tasklist', timeout=30),
            MagicMock(stdout='"Image Name","PID"\n"copilot.exe","1234"'),
        ]
        assert check_copilot_processes() == 0
        assert check_copilot_processes() == 1
        assert mock_run.call_count == 2


class TestWaitForProcessCleanup:
    """Tests for wait_for_process_cleanup."""

    @patch('pokepoke.process_utils.os')
    def test_returns_immediately_on_non_windows(self, mock_os):
        mock_os.name = 'posix'
        wait_for_process_cleanup(max_wait=0.1)

    @patch('pokepoke.process_utils.check_copilot_processes')
    @patch('pokepoke.process_utils.os')
    def test_returns_when_no_processes(self, mock_os, mock_check):
        mock_os.name = 'nt'
        mock_check.return_value = 0
        wait_for_process_cleanup(max_wait=0.1)
        mock_check.assert_called_once()

    @patch('pokepoke.process_utils.check_copilot_processes')
    @patch('pokepoke.process_utils.os')
    def test_waits_for_processes_to_terminate(self, mock_os, mock_check):
        mock_os.name = 'nt'
        mock_check.side_effect = [1, 1, 0]
        wait_for_process_cleanup(max_wait=1.0)
        assert mock_check.call_count == 3


class TestShutdownCopilotClient:
    """Tests for shutdown_copilot_client."""

    @pytest.mark.asyncio
    async def test_graceful_stop(self):
        client = AsyncMock()
        client.stop = AsyncMock()
        with patch('pokepoke.process_utils.os') as mock_os:
            mock_os.name = 'posix'
            await shutdown_copilot_client(client)
        client.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_graceful_stop_with_windows_cleanup(self):
        client = AsyncMock()
        client.stop = AsyncMock()
        with (
            patch('pokepoke.process_utils.os') as mock_os,
            patch('pokepoke.process_utils.wait_for_process_cleanup') as mock_cleanup,
        ):
            mock_os.name = 'nt'
            await shutdown_copilot_client(client)
        mock_cleanup.assert_called_with(max_wait=2.0)

    @pytest.mark.asyncio
    async def test_timeout_then_force_stop(self):
        client = AsyncMock()
        client.stop = AsyncMock(side_effect=asyncio.TimeoutError)
        client.force_stop = AsyncMock()
        with patch('pokepoke.process_utils.os') as mock_os:
            mock_os.name = 'posix'
            # asyncio.wait_for wraps, so we need to mock at that level
            with patch('pokepoke.process_utils.asyncio.wait_for', side_effect=TimeoutError):
                await shutdown_copilot_client(client)

    @pytest.mark.asyncio
    async def test_unicode_decode_error_suppressed(self):
        client = AsyncMock()
        client.stop = AsyncMock(side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'err'))
        with patch('pokepoke.process_utils.asyncio.sleep', new_callable=AsyncMock):
            await shutdown_copilot_client(client)

    @pytest.mark.asyncio
    async def test_generic_exception_handled(self):
        client = AsyncMock()
        client.stop = AsyncMock(side_effect=RuntimeError("boom"))
        with patch('pokepoke.process_utils.asyncio.sleep', new_callable=AsyncMock):
            await shutdown_copilot_client(client)
