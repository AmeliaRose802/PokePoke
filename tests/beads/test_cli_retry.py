"""Tests for pokepoke.beads.cli_retry — transient detection and retry wrapper."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.beads.cli_retry import _is_transient_cli_error, _run_bd_with_retry

# ---------------------------------------------------------------------------
# _is_transient_cli_error
# ---------------------------------------------------------------------------


class TestIsTransientCliError:
    """Cover all branches of _is_transient_cli_error."""

    def test_timeout_expired_is_transient(self) -> None:
        exc = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        assert _is_transient_cli_error(exc) is True

    def test_oserror_is_transient(self) -> None:
        assert _is_transient_cli_error(OSError("permission denied")) is True

    def test_called_process_error_jsonl_lock(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="jsonl lock contention")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_jsonl_access_denied(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="jsonl access is denied")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_failed_to_replace_jsonl(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="failed to replace jsonl file")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_lock_could_not(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="could not acquire lock")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_lock_failed(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="lock failed to acquire")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_daemon_not_ready(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="daemon not ready")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_daemon_connect(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="daemon connect failure")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_connection_refused(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="connection refused")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_connection_timed_out(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="connection timed out")
        assert _is_transient_cli_error(exc) is True

    def test_called_process_error_non_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="item not found")
        assert _is_transient_cli_error(exc) is False

    def test_called_process_error_none_output(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", output=None, stderr=None)
        assert _is_transient_cli_error(exc) is False

    def test_generic_exception_not_transient(self) -> None:
        assert _is_transient_cli_error(ValueError("bad")) is False

    def test_called_process_error_stdout_match(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", output="jsonl lock issue", stderr="")
        assert _is_transient_cli_error(exc) is True


# ---------------------------------------------------------------------------
# _run_bd_with_retry
# ---------------------------------------------------------------------------


class TestRunBdWithRetry:
    """Cover retry wrapper logic."""

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_success_on_first_attempt(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=["ready"], returncode=0)
        result = _run_bd_with_retry(["ready"], base_delay=0.01)
        assert result.returncode == 0
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_retry_on_transient_then_succeed(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        transient = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        ok = subprocess.CompletedProcess(args=["ready"], returncode=0)
        mock_run.side_effect = [transient, ok]

        result = _run_bd_with_retry(["ready"], max_attempts=3, base_delay=0.01)
        assert result.returncode == 0
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once()

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_raises_after_max_attempts(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        transient = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        mock_run.side_effect = [transient, transient, transient]

        with pytest.raises(subprocess.TimeoutExpired):
            _run_bd_with_retry(["ready"], max_attempts=3, base_delay=0.01)
        assert mock_run.call_count == 3

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_non_transient_raises_immediately(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        non_transient = subprocess.CalledProcessError(1, "bd", stderr="item not found")
        mock_run.side_effect = non_transient

        with pytest.raises(subprocess.CalledProcessError):
            _run_bd_with_retry(["show"], max_attempts=3, base_delay=0.01)
        mock_run.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_exponential_backoff_delays(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        transient = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        ok = subprocess.CompletedProcess(args=["ready"], returncode=0)
        mock_run.side_effect = [transient, transient, ok]

        _run_bd_with_retry(["ready"], max_attempts=3, base_delay=1.0)
        assert mock_sleep.call_count == 2
        # With jitter enabled, delays should be in range [base*0.5, base*1.5]
        # Attempt 0: base_delay * 2^0 = 1.0, jittered: [0.5, 1.5]
        # Attempt 1: base_delay * 2^1 = 2.0, jittered: [1.0, 3.0]
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert 0.5 <= delays[0] <= 1.5
        assert 1.0 <= delays[1] <= 3.0

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_empty_args_uses_unknown_label(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        result = _run_bd_with_retry([], base_delay=0.01)
        assert result.returncode == 0

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_passes_kwargs_to_run_bd(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(args=["ready"], returncode=0)
        _run_bd_with_retry(
            ["ready"],
            check=False,
            timeout=60,
            cwd="/tmp",
            backend=None,
            base_delay=0.01,
        )
        mock_run.assert_called_once_with(
            ["ready"], check=False, timeout=60, cwd="/tmp", backend=None,
        )

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.beads.beads_query._run_bd")
    def test_oserror_retried(self, mock_run: MagicMock, mock_sleep: MagicMock) -> None:
        oserr = OSError("permission denied")
        ok = subprocess.CompletedProcess(args=["ready"], returncode=0)
        mock_run.side_effect = [oserr, ok]

        result = _run_bd_with_retry(["ready"], max_attempts=2, base_delay=0.01)
        assert result.returncode == 0
        assert mock_run.call_count == 2
