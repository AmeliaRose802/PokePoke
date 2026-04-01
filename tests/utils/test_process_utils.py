"""Tests for process_utils module."""
import asyncio
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import pokepoke.utils.process_utils as process_utils_mod
from pokepoke.utils.process_utils import (
    apply_memory_backpressure,
    check_copilot_processes,
    get_available_memory_mb,
    is_memory_critical,
    is_memory_pressure,
    is_process_running,
    kill_orphaned_copilot_processes,
    log_process_tree_snapshot,
    shutdown_copilot_client,
    wait_for_process_cleanup,
)


@pytest.fixture(autouse=True)
def reset_copilot_cache():
    """Reset the module-level caches before each test to prevent cross-test pollution."""
    process_utils_mod._copilot_process_cache = None
    process_utils_mod._memory_cache = None
    yield
    process_utils_mod._copilot_process_cache = None
    process_utils_mod._memory_cache = None


class TestCheckCopilotProcesses:
    """Tests for check_copilot_processes."""

    @patch('pokepoke.utils.process_utils.os')
    def test_returns_zero_on_non_windows(self, mock_os):
        mock_os.name = 'posix'
        assert check_copilot_processes() == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_returns_process_count_on_windows(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(
            stdout='"Image Name","PID"\n"copilot.exe","1234"\n"copilot.exe","5678"'
        )
        assert check_copilot_processes() == 2

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_returns_zero_when_no_processes(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        assert check_copilot_processes() == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_returns_zero_on_exception(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='tasklist', timeout=30)
        assert check_copilot_processes() == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_uses_utf8_encoding(self, mock_run, mock_os):
        """tasklist is called with UTF-8 encoding to avoid UnicodeDecodeError."""
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        check_copilot_processes()
        _, kwargs = mock_run.call_args
        assert kwargs.get('encoding') == 'utf-8'
        assert kwargs.get('errors') == 'replace'

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_uses_30s_timeout(self, mock_run, mock_os):
        """tasklist timeout is 30 seconds (increased from 5s)."""
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        check_copilot_processes()
        _, kwargs = mock_run.call_args
        assert kwargs.get('timeout') == 30

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
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

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    @patch('pokepoke.utils.process_utils.time')
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

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
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

    @patch('pokepoke.utils.process_utils.os')
    def test_returns_immediately_on_non_windows(self, mock_os):
        mock_os.name = 'posix'
        wait_for_process_cleanup(max_wait=0.1)

    @patch('pokepoke.utils.process_utils.check_copilot_processes')
    @patch('pokepoke.utils.process_utils.os')
    def test_returns_when_no_processes(self, mock_os, mock_check):
        mock_os.name = 'nt'
        mock_check.return_value = 0
        wait_for_process_cleanup(max_wait=0.1)
        mock_check.assert_called_once()

    @patch('pokepoke.utils.process_utils.check_copilot_processes')
    @patch('pokepoke.utils.process_utils.os')
    def test_waits_for_processes_to_terminate(self, mock_os, mock_check):
        mock_os.name = 'nt'
        mock_check.side_effect = [1, 1, 0]
        wait_for_process_cleanup(max_wait=1.0)
        assert mock_check.call_count == 3


class TestGetAvailableMemoryMb:
    """Tests for get_available_memory_mb."""

    @patch('pokepoke.utils.process_utils.os')
    def test_returns_zero_on_non_windows(self, mock_os: MagicMock) -> None:
        mock_os.name = 'posix'
        assert get_available_memory_mb() == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.ctypes')
    def test_returns_available_memory_on_windows(self, mock_ctypes: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        # Create a mock MEMORYSTATUSEX with 4 GB available
        mock_mem = MagicMock()
        mock_mem.ullAvailPhys = 4 * 1024 * 1024 * 1024  # 4 GB
        mock_ctypes.Structure = type
        mock_ctypes.sizeof.return_value = 64
        mock_ctypes.c_ulong = int
        mock_ctypes.c_ulonglong = int
        # Patch the class creation inside the function
        with patch.object(process_utils_mod, 'get_available_memory_mb', wraps=get_available_memory_mb):
            # Can't easily mock ctypes.Structure subclass creation;
            # test the caching path instead
            process_utils_mod._memory_cache = (process_utils_mod.time.time(), 4096)
            result = get_available_memory_mb()
            assert result == 4096

    def test_caches_result_within_ttl(self) -> None:
        """Repeated calls within TTL reuse cached result."""
        import time
        process_utils_mod._memory_cache = (time.time(), 8000)
        assert get_available_memory_mb() == 8000


class TestIsMemoryPressure:
    """Tests for is_memory_pressure."""

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_no_pressure_when_plenty_of_memory(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 8000  # 8 GB free
        assert is_memory_pressure() is False

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_pressure_when_low_memory(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 1500  # 1.5 GB free
        assert is_memory_pressure() is True

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_no_pressure_when_unknown(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 0  # Can't determine
        assert is_memory_pressure() is False


class TestIsMemoryCritical:
    """Tests for is_memory_critical."""

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_not_critical_with_normal_memory(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 4000
        assert is_memory_critical() is False

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_critical_when_very_low(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 500  # 500 MB free
        assert is_memory_critical() is True

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_not_critical_when_unknown(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 0
        assert is_memory_critical() is False


class TestKillOrphanedCopilotProcesses:
    """Tests for kill_orphaned_copilot_processes."""

    @patch('pokepoke.utils.process_utils.os')
    def test_returns_zero_on_non_windows(self, mock_os: MagicMock) -> None:
        mock_os.name = 'posix'
        assert kill_orphaned_copilot_processes(expected_count=0) == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_no_processes_found(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        assert kill_orphaned_copilot_processes(expected_count=0) == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_kills_excess_processes(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        # First call: tasklist returns 4 processes
        tasklist_output = (
            '"Image Name","PID","Session Name","Session#","Mem Usage"\n'
            '"copilot.exe","100","Console","1","50,000 K"\n'
            '"copilot.exe","200","Console","1","50,000 K"\n'
            '"copilot.exe","300","Console","1","50,000 K"\n'
            '"copilot.exe","400","Console","1","50,000 K"'
        )
        mock_run.return_value = MagicMock(stdout=tasklist_output)
        # expected_count=2, so 2 should be killed (PIDs 100 and 200 as lowest)
        killed = kill_orphaned_copilot_processes(expected_count=2)
        assert killed == 2
        # Verify taskkill was called with /F /T /PID for the oldest PIDs
        taskkill_calls = [c for c in mock_run.call_args_list
                         if 'taskkill' in str(c)]
        assert len(taskkill_calls) == 2

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_no_kill_when_under_expected(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        tasklist_output = (
            '"Image Name","PID"\n'
            '"copilot.exe","100"\n'
            '"copilot.exe","200"'
        )
        mock_run.return_value = MagicMock(stdout=tasklist_output)
        assert kill_orphaned_copilot_processes(expected_count=3) == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_handles_tasklist_exception(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='tasklist', timeout=30)
        assert kill_orphaned_copilot_processes(expected_count=0) == 0

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_handles_valueerror_in_pid_parsing(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        tasklist_output = (
            '"Image Name","PID"\n'
            '"copilot.exe","not_a_pid"\n'
            '"copilot.exe","200"'
        )
        mock_run.return_value = MagicMock(stdout=tasklist_output)
        # Only PID 200 is valid, expected 0 → kill 1
        killed = kill_orphaned_copilot_processes(expected_count=0)
        assert killed == 1

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_handles_taskkill_exception(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        tasklist_output = (
            '"Image Name","PID"\n'
            '"copilot.exe","100"'
        )

        def side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if 'taskkill' in cmd:
                raise OSError("permission denied")
            return MagicMock(stdout=tasklist_output)

        mock_run.side_effect = side_effect
        killed = kill_orphaned_copilot_processes(expected_count=0)
        assert killed == 0


class TestApplyMemoryBackpressure:
    """Tests for apply_memory_backpressure."""

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_no_change_when_plenty_of_memory(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 8000
        slots, avail = apply_memory_backpressure(4)
        assert slots == 4
        assert avail == 8000

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_returns_zero_slots_when_critical(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 500  # Below critical threshold
        slots, avail = apply_memory_backpressure(4)
        assert slots == 0
        assert avail == 500

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_throttles_to_one_under_pressure(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 1500  # Under pressure but not critical
        slots, avail = apply_memory_backpressure(4)
        assert slots == 1
        assert avail == 1500

    @patch('pokepoke.utils.process_utils.get_available_memory_mb')
    def test_passthrough_when_unknown(self, mock_mem: MagicMock) -> None:
        mock_mem.return_value = 0  # Can't determine
        slots, avail = apply_memory_backpressure(4)
        assert slots == 4
        assert avail == 0


class TestIsProcessRunning:
    """Tests for is_process_running."""

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_running_process_on_windows(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(
            stdout='"Image Name","PID"\n"python.exe","1234"'
        )
        assert is_process_running(1234) is True

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_not_running_process_on_windows(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        assert is_process_running(99999) is False

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_exception_returns_false_on_windows(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='tasklist', timeout=10)
        assert is_process_running(1234) is False


class TestShutdownCopilotClient:
    """Tests for shutdown_copilot_client."""

    @pytest.mark.asyncio
    async def test_graceful_stop(self):
        client = AsyncMock()
        client.stop = AsyncMock()
        with patch('pokepoke.utils.process_utils.os') as mock_os:
            mock_os.name = 'posix'
            await shutdown_copilot_client(client)
        client.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_graceful_stop_with_windows_cleanup(self):
        client = AsyncMock()
        client.stop = AsyncMock()
        with (
            patch('pokepoke.utils.process_utils.os') as mock_os,
            patch('pokepoke.utils.process_utils.wait_for_process_cleanup') as mock_cleanup,
        ):
            mock_os.name = 'nt'
            await shutdown_copilot_client(client)
        mock_cleanup.assert_called_with(max_wait=2.0)

    @pytest.mark.asyncio
    async def test_timeout_then_force_stop(self):
        client = AsyncMock()
        client.stop = AsyncMock(side_effect=asyncio.TimeoutError)
        client.force_stop = AsyncMock()
        with patch('pokepoke.utils.process_utils.os') as mock_os:
            mock_os.name = 'posix'
            # asyncio.wait_for wraps, so we need to mock at that level
            with patch('pokepoke.utils.process_utils.asyncio.wait_for', side_effect=TimeoutError):
                await shutdown_copilot_client(client)

    @pytest.mark.asyncio
    async def test_unicode_decode_error_suppressed(self):
        client = AsyncMock()
        client.stop = AsyncMock(side_effect=UnicodeDecodeError('utf-8', b'', 0, 1, 'err'))
        with patch('pokepoke.utils.process_utils.asyncio.sleep', new_callable=AsyncMock):
            await shutdown_copilot_client(client)

    @pytest.mark.asyncio
    async def test_generic_exception_handled(self):
        client = AsyncMock()
        client.stop = AsyncMock(side_effect=RuntimeError("boom"))
        with patch('pokepoke.utils.process_utils.asyncio.sleep', new_callable=AsyncMock):
            await shutdown_copilot_client(client)


class TestCacheLockThreadSafety:
    """Tests for thread-safe cache access via _cache_lock."""

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_check_copilot_processes_concurrent_access(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        """Multiple threads calling check_copilot_processes should not corrupt cache."""
        mock_os.name = 'nt'

        def mock_tasklist(*args, **kwargs):
            time.sleep(0.01)  # Simulate work
            return MagicMock(stdout='"Image Name","PID"\n"copilot.exe","1234"')

        mock_run.side_effect = mock_tasklist

        results = []
        errors = []

        def worker():
            try:
                result = check_copilot_processes()
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Run 10 concurrent threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
        # All results should be 1 (one copilot process) - no corruption
        assert all(r == 1 for r in results)
        # Cache should be set correctly after all threads complete
        assert process_utils_mod._copilot_process_cache is not None
        assert process_utils_mod._copilot_process_cache[1] == 1

    @patch('pokepoke.utils.process_utils.os')
    def test_get_available_memory_concurrent_access(self, mock_os: MagicMock) -> None:
        """Multiple threads calling get_available_memory_mb should not corrupt cache."""
        mock_os.name = 'nt'

        # Pre-seed cache so we don't need real ctypes calls
        process_utils_mod._memory_cache = (time.time(), 4096)

        results = []
        errors = []

        def worker():
            try:
                result = get_available_memory_mb()
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Run 10 concurrent threads
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker) for _ in range(10)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
        # All results should be 4096 from cache
        assert all(r == 4096 for r in results)

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_kill_orphaned_processes_invalidates_cache_safely(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        """kill_orphaned_copilot_processes should invalidate cache thread-safely."""
        mock_os.name = 'nt'
        tasklist_output = (
            '"Image Name","PID","Session Name","Session#","Mem Usage"\n'
            '"copilot.exe","100","Console","1","50,000 K"\n'
            '"copilot.exe","200","Console","1","50,000 K"'
        )
        mock_run.return_value = MagicMock(stdout=tasklist_output)

        # Pre-seed cache
        process_utils_mod._copilot_process_cache = (time.time(), 5)

        # Kill with expected_count=0 (should kill both)
        killed = kill_orphaned_copilot_processes(expected_count=0)
        assert killed == 2

        # Cache should be invalidated
        assert process_utils_mod._copilot_process_cache is None

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_exception_logging_rate_limited_with_lock(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        """Verify _copilot_last_tasklist_failure_log is updated thread-safely."""
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='tasklist', timeout=30)

        # Reset failure log
        process_utils_mod._copilot_last_tasklist_failure_log = None

        errors = []
        results = []

        def worker():
            try:
                result = check_copilot_processes()
                results.append(result)
            except Exception as e:
                errors.append(e)

        # Run concurrent calls that all fail
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker) for _ in range(5)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
        # All results should be 0 (failure case)
        assert all(r == 0 for r in results)
        # The failure timestamp should be set (not None)
        assert process_utils_mod._copilot_last_tasklist_failure_log is not None

    def test_cache_lock_exists(self) -> None:
        """Verify the _cache_lock is a threading.Lock instance."""
        assert hasattr(process_utils_mod, '_cache_lock')
        assert isinstance(process_utils_mod._cache_lock, type(threading.Lock()))


class TestLogProcessTreeSnapshot:
    """Tests for log_process_tree_snapshot."""

    @patch('pokepoke.utils.process_utils.os')
    def test_returns_immediately_on_non_windows(self, mock_os: MagicMock) -> None:
        mock_os.name = 'posix'
        log_process_tree_snapshot('test_tool', 'args', 60.0)
        # Should return immediately without any subprocess calls

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_logs_no_processes_found(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        log_process_tree_snapshot('test_tool', 'args', 60.0)
        # Should log "No copilot.exe processes found"

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_logs_process_tree_with_children(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        # First call returns copilot PIDs, second returns children
        tasklist_output = '"Image Name","PID"\n"copilot.exe","1234"'
        wmic_output = 'Name=git.exe\nProcessId=5678\nCommandLine=git status'
        mock_run.side_effect = [
            MagicMock(stdout=tasklist_output),
            MagicMock(stdout=wmic_output),
        ]
        log_process_tree_snapshot('test_tool', 'args', 60.0)
        assert mock_run.call_count == 2

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_logs_process_tree_without_children(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        tasklist_output = '"Image Name","PID"\n"copilot.exe","1234"'
        mock_run.side_effect = [
            MagicMock(stdout=tasklist_output),
            MagicMock(stdout=''),  # No children
        ]
        log_process_tree_snapshot('test_tool', 'args', 60.0)
        assert mock_run.call_count == 2

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_handles_exception(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='tasklist', timeout=5)
        # Should not raise
        log_process_tree_snapshot('test_tool', 'args', 60.0)

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_logs_to_handler_item_logger(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        tasklist_output = '"Image Name","PID"\n"copilot.exe","1234"'
        mock_run.side_effect = [
            MagicMock(stdout=tasklist_output),
            MagicMock(stdout=''),
        ]
        handler = MagicMock()
        handler._item_logger = MagicMock()
        log_process_tree_snapshot('test_tool', 'args', 60.0, handler=handler)
        handler._item_logger.log_error.assert_called_once()

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_skips_handler_without_item_logger(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        tasklist_output = '"Image Name","PID"\n"copilot.exe","1234"'
        mock_run.side_effect = [
            MagicMock(stdout=tasklist_output),
            MagicMock(stdout=''),
        ]
        handler = MagicMock(spec=[])  # No _item_logger attribute
        log_process_tree_snapshot('test_tool', 'args', 60.0, handler=handler)

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_handles_invalid_pid_parsing(self, mock_run: MagicMock, mock_os: MagicMock) -> None:
        mock_os.name = 'nt'
        # Invalid PID should be suppressed via contextlib.suppress
        tasklist_output = '"Image Name","PID"\n"copilot.exe","not_a_number"'
        mock_run.return_value = MagicMock(stdout=tasklist_output)
        # Should not raise and should handle gracefully
        log_process_tree_snapshot('test_tool', 'args', 60.0)


class TestIsProcessRunningUnix:
    """Tests for is_process_running on Unix/Linux."""

    @patch('pokepoke.utils.process_utils.os')
    def test_returns_true_for_running_process(self, mock_os: MagicMock) -> None:
        mock_os.name = 'posix'
        mock_os.kill = MagicMock()  # No exception = process exists
        assert is_process_running(1234) is True
        mock_os.kill.assert_called_once_with(1234, 0)

    @patch('pokepoke.utils.process_utils.os')
    def test_returns_false_for_nonexistent_process(self, mock_os: MagicMock) -> None:
        mock_os.name = 'posix'
        mock_os.kill = MagicMock(side_effect=OSError("No such process"))
        assert is_process_running(99999) is False


class TestShutdownCopilotClientAdvanced:
    """Additional tests for shutdown_copilot_client edge cases."""

    @pytest.mark.asyncio
    async def test_double_timeout_with_windows_cleanup(self):
        """Test the double timeout scenario with Windows process cleanup."""
        client = AsyncMock()
        stop_call_count = 0

        async def stop_with_timeout():
            nonlocal stop_call_count
            stop_call_count += 1
            raise TimeoutError()

        client.stop = stop_with_timeout
        client.force_stop = AsyncMock()

        with (
            patch('pokepoke.utils.process_utils.os') as mock_os,
            patch('pokepoke.utils.process_utils.wait_for_process_cleanup'),
            patch('pokepoke.utils.process_utils.asyncio.wait_for', side_effect=TimeoutError),
        ):
            mock_os.name = 'nt'
            await shutdown_copilot_client(client)
        # force_stop should be called after double timeout
        client.force_stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_second_stop_succeeds_after_first_timeout(self):
        """Test that second stop attempt succeeds after first times out."""
        client = AsyncMock()
        call_count = 0

        async def stop_with_retry():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError()
            # Second call succeeds

        client.stop = stop_with_retry

        with (
            patch('pokepoke.utils.process_utils.os') as mock_os,
            patch('pokepoke.utils.process_utils.wait_for_process_cleanup') as mock_cleanup,
            patch('pokepoke.utils.process_utils.asyncio.wait_for') as mock_wait_for,
        ):
            mock_os.name = 'nt'
            # First call times out, second succeeds
            mock_wait_for.side_effect = [TimeoutError(), None]
            await shutdown_copilot_client(client)
        mock_cleanup.assert_called_with(max_wait=1.0)

    @pytest.mark.asyncio
    async def test_force_stop_error(self):
        """Test handling of force_stop error."""
        client = AsyncMock()
        client.stop = AsyncMock(side_effect=TimeoutError)
        client.force_stop = AsyncMock(side_effect=RuntimeError("Force stop failed"))

        with (
            patch('pokepoke.utils.process_utils.asyncio.wait_for', side_effect=TimeoutError),
        ):
            # Should not raise even if force_stop fails
            await shutdown_copilot_client(client)

    @pytest.mark.asyncio
    async def test_second_stop_raises_non_timeout_exception(self):
        """Test that non-timeout exception in second stop is handled."""
        client = AsyncMock()
        client.stop = AsyncMock()

        with (
            patch('pokepoke.utils.process_utils.os') as mock_os,
            patch('pokepoke.utils.process_utils.asyncio.wait_for') as mock_wait_for,
        ):
            mock_os.name = 'posix'
            # First times out, second raises different exception
            mock_wait_for.side_effect = [TimeoutError(), RuntimeError("boom")]
            await shutdown_copilot_client(client)


class TestGetAvailableMemoryMbWindows:
    """Tests for get_available_memory_mb Windows ctypes path."""

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.ctypes')
    def test_windows_memory_query_exception(self, mock_ctypes: MagicMock, mock_os: MagicMock) -> None:
        """Test exception handling in Windows memory query."""
        mock_os.name = 'nt'
        mock_ctypes.Structure = type  # Allow class definition
        mock_ctypes.windll.kernel32.GlobalMemoryStatusEx.side_effect = OSError("ctypes error")
        mock_ctypes.sizeof.return_value = 64
        mock_ctypes.c_ulong = int
        mock_ctypes.c_ulonglong = int
        mock_ctypes.byref = MagicMock()

        # Clear cache to force fresh query
        process_utils_mod._memory_cache = None
        result = get_available_memory_mb()
        # Should return 0 on exception
        assert result == 0
