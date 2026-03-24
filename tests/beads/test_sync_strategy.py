"""Tests for sync_strategy module — SyncStrategy, DaemonSync, ExplicitSync."""

import subprocess
from unittest.mock import Mock, patch

import pytest

from pokepoke.beads.beads_query import (
    BD_CONFIG,
    BR_CONFIG,
    CLIBackendConfig,
    get_active_backend,
    set_active_backend,
)
from pokepoke.beads.sync_strategy import (
    DaemonSync,
    ExplicitSync,
    SyncStrategy,
    _is_transient_br_sync_error,
    _is_transient_jsonl_sync_error,
    get_active_sync_strategy,
    set_active_sync_strategy,
)

# _run_cli is lazily imported inside strategy methods, so we patch at source.
_RUN_CLI_PATH = "pokepoke.beads.beads_query._run_cli"
_SUBPROCESS_RUN_PATH = "subprocess.run"


# ---------------------------------------------------------------------------
# _is_transient_jsonl_sync_error
# ---------------------------------------------------------------------------


class TestIsTransientJsonlSyncError:
    """Regression tests ensuring the helper was moved correctly."""

    def test_access_denied_with_jsonl(self) -> None:
        assert _is_transient_jsonl_sync_error("Access is denied to jsonl file") is True

    def test_failed_to_replace_jsonl(self) -> None:
        assert _is_transient_jsonl_sync_error("failed to replace jsonl file") is True

    def test_jsonl_hash_mismatch(self) -> None:
        assert _is_transient_jsonl_sync_error("jsonl file hash mismatch") is True

    def test_unrelated_error(self) -> None:
        assert _is_transient_jsonl_sync_error("some other error") is False

    def test_access_denied_without_jsonl(self) -> None:
        assert _is_transient_jsonl_sync_error("Access is denied") is False


# ---------------------------------------------------------------------------
# _is_transient_br_sync_error
# ---------------------------------------------------------------------------


class TestIsTransientBrSyncError:

    def test_index_lock_is_transient(self) -> None:
        assert _is_transient_br_sync_error("fatal: Unable to create 'index.lock': File exists") is True

    def test_lock_could_not_acquire(self) -> None:
        assert _is_transient_br_sync_error("lock: could not acquire file lock") is True

    def test_lock_failed(self) -> None:
        assert _is_transient_br_sync_error("lock: failed to obtain lock") is True

    def test_connection_refused(self) -> None:
        assert _is_transient_br_sync_error("connection refused by remote") is True

    def test_connection_timed_out(self) -> None:
        assert _is_transient_br_sync_error("connection timed out") is True

    def test_merge_conflict_not_transient(self) -> None:
        assert _is_transient_br_sync_error("merge conflict in items.jsonl") is False

    def test_unrelated_error(self) -> None:
        assert _is_transient_br_sync_error("unknown fatal error") is False

    def test_empty_string(self) -> None:
        assert _is_transient_br_sync_error("") is False


# ---------------------------------------------------------------------------
# DaemonSync
# ---------------------------------------------------------------------------


class TestDaemonSync:

    @patch(_RUN_CLI_PATH)
    def test_sync_success_first_attempt(self, mock_run_cli: Mock) -> None:
        mock_run_cli.return_value = Mock(returncode=0, stdout="ok", stderr="")
        strategy = DaemonSync(backend=BD_CONFIG)

        result = strategy.sync()

        assert result.returncode == 0
        mock_run_cli.assert_called_once_with(
            ["sync"], backend=BD_CONFIG, check=False, timeout=60,
        )

    @patch("pokepoke.beads.sync_strategy.time.sleep")
    @patch(_RUN_CLI_PATH)
    def test_retries_on_jsonl_lock_error(
        self, mock_run_cli: Mock, mock_sleep: Mock,
    ) -> None:
        fail = Mock(returncode=1, stdout="failed to replace jsonl file", stderr="")
        ok = Mock(returncode=0, stdout="", stderr="")
        mock_run_cli.side_effect = [fail, ok]
        strategy = DaemonSync(backend=BD_CONFIG)

        result = strategy.sync(max_attempts=3, base_delay=0.1)

        assert result.returncode == 0
        assert mock_run_cli.call_count == 2
        mock_sleep.assert_called_once()

    @patch(_RUN_CLI_PATH)
    def test_returns_immediately_on_non_transient_error(
        self, mock_run_cli: Mock,
    ) -> None:
        fail = Mock(returncode=1, stdout="some random error", stderr="")
        mock_run_cli.return_value = fail
        strategy = DaemonSync(backend=BD_CONFIG)

        result = strategy.sync(max_attempts=3)

        assert result.returncode == 1
        assert mock_run_cli.call_count == 1

    @patch("pokepoke.beads.sync_strategy.time.sleep")
    @patch(_RUN_CLI_PATH)
    def test_exponential_backoff_delay(
        self, mock_run_cli: Mock, mock_sleep: Mock,
    ) -> None:
        fail = Mock(returncode=1, stdout="jsonl file hash mismatch", stderr="")
        ok = Mock(returncode=0, stdout="", stderr="")
        mock_run_cli.side_effect = [fail, fail, ok]
        strategy = DaemonSync(backend=BD_CONFIG)

        strategy.sync(max_attempts=4, base_delay=1.0)

        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch(_RUN_CLI_PATH)
    def test_passes_timeout(self, mock_run_cli: Mock) -> None:
        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        strategy = DaemonSync(backend=BD_CONFIG)

        strategy.sync(timeout=42)

        _, kwargs = mock_run_cli.call_args
        assert kwargs["timeout"] == 42

    @patch(_RUN_CLI_PATH)
    def test_uses_explicit_backend(self, mock_run_cli: Mock) -> None:
        custom = CLIBackendConfig(binary="custom-bd")
        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        strategy = DaemonSync(backend=custom)

        strategy.sync()

        _, kwargs = mock_run_cli.call_args
        assert kwargs["backend"].binary == "custom-bd"

    @patch(_RUN_CLI_PATH)
    def test_falls_back_to_active_backend(self, mock_run_cli: Mock) -> None:
        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        strategy = DaemonSync()  # No explicit backend

        strategy.sync()

        _, kwargs = mock_run_cli.call_args
        assert kwargs["backend"].binary == get_active_backend().binary


# ---------------------------------------------------------------------------
# ExplicitSync
# ---------------------------------------------------------------------------


class TestExplicitSync:

    @patch("pokepoke.beads.sync_strategy.ExplicitSync._git_publish_sync")
    @patch(_RUN_CLI_PATH)
    def test_sync_success_calls_git_publish(
        self, mock_run_cli: Mock, mock_git_pub: Mock,
    ) -> None:
        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        strategy = ExplicitSync(backend=BR_CONFIG)

        result = strategy.sync()

        assert result.returncode == 0
        mock_git_pub.assert_called_once()

    @patch("pokepoke.beads.sync_strategy.ExplicitSync._git_publish_sync")
    @patch("pokepoke.beads.sync_strategy.time.sleep")
    @patch(_RUN_CLI_PATH)
    def test_retries_on_index_lock_error(
        self, mock_run_cli: Mock, mock_sleep: Mock, mock_git_pub: Mock,
    ) -> None:
        fail = Mock(
            returncode=1,
            stdout="fatal: Unable to create 'index.lock': File exists",
            stderr="",
        )
        ok = Mock(returncode=0, stdout="", stderr="")
        mock_run_cli.side_effect = [fail, ok]
        strategy = ExplicitSync(backend=BR_CONFIG)

        result = strategy.sync(max_attempts=3, base_delay=0.1)

        assert result.returncode == 0
        assert mock_run_cli.call_count == 2
        mock_sleep.assert_called_once()
        mock_git_pub.assert_called_once()

    @patch("pokepoke.beads.sync_strategy.ExplicitSync._git_publish_sync")
    @patch("pokepoke.beads.sync_strategy.time.sleep")
    @patch(_RUN_CLI_PATH)
    def test_retries_on_connection_refused(
        self, mock_run_cli: Mock, mock_sleep: Mock, mock_git_pub: Mock,
    ) -> None:
        fail = Mock(returncode=1, stdout="connection refused", stderr="")
        ok = Mock(returncode=0, stdout="", stderr="")
        mock_run_cli.side_effect = [fail, ok]
        strategy = ExplicitSync(backend=BR_CONFIG)

        result = strategy.sync(max_attempts=3, base_delay=0.1)

        assert result.returncode == 0
        assert mock_run_cli.call_count == 2

    @patch("pokepoke.beads.sync_strategy.ExplicitSync._git_publish_sync")
    @patch(_RUN_CLI_PATH)
    def test_does_not_retry_merge_conflict(
        self, mock_run_cli: Mock, mock_git_pub: Mock,
    ) -> None:
        fail = Mock(returncode=1, stdout="merge conflict in items.jsonl", stderr="")
        mock_run_cli.return_value = fail
        strategy = ExplicitSync(backend=BR_CONFIG)

        result = strategy.sync(max_attempts=3)

        assert result.returncode == 1
        assert mock_run_cli.call_count == 1
        mock_git_pub.assert_not_called()

    @patch("pokepoke.beads.sync_strategy.ExplicitSync._git_publish_sync")
    @patch(_RUN_CLI_PATH)
    def test_passes_timeout(
        self, mock_run_cli: Mock, mock_git_pub: Mock,
    ) -> None:
        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        strategy = ExplicitSync(backend=BR_CONFIG)

        strategy.sync(timeout=99)

        _, kwargs = mock_run_cli.call_args
        assert kwargs["timeout"] == 99

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_no_changes(self, mock_subprocess: Mock) -> None:
        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        ExplicitSync._git_publish_sync()

        # Only git status should be called; no add/commit/push
        mock_subprocess.assert_called_once()
        assert mock_subprocess.call_args[0][0] == ["git", "status", "--porcelain", ".beads/"]

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_with_changes(self, mock_subprocess: Mock) -> None:
        mock_subprocess.side_effect = [
            Mock(stdout=" M .beads/items.jsonl", returncode=0),   # status
            Mock(stdout="", returncode=0),                         # add
            Mock(stdout="", returncode=0),                         # commit
            Mock(stdout="", returncode=0),                         # push
        ]

        ExplicitSync._git_publish_sync()

        assert mock_subprocess.call_count == 4
        calls = mock_subprocess.call_args_list
        assert calls[0][0][0] == ["git", "status", "--porcelain", ".beads/"]
        assert calls[1][0][0] == ["git", "add", ".beads/"]
        assert calls[2][0][0] == ["git", "commit", "-m", "beads: sync database"]
        assert calls[3][0][0] == ["git", "push"]

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_tolerates_push_failure(
        self, mock_subprocess: Mock,
    ) -> None:
        mock_subprocess.side_effect = [
            Mock(stdout=" M .beads/items.jsonl", returncode=0),
            Mock(stdout="", returncode=0),
            Mock(stdout="", returncode=0),
            subprocess.CalledProcessError(1, "git push"),
        ]
        # Should not raise — failure is logged but tolerated
        ExplicitSync._git_publish_sync()

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_tolerates_timeout(
        self, mock_subprocess: Mock,
    ) -> None:
        mock_subprocess.side_effect = [
            subprocess.TimeoutExpired("git", 10),
        ]
        # Should not raise
        ExplicitSync._git_publish_sync()

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_returns_true_no_changes(self, mock_subprocess: Mock) -> None:
        """_git_publish_sync returns True when there are no changes."""
        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        result = ExplicitSync._git_publish_sync()
        assert result is True

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_returns_true_on_success(self, mock_subprocess: Mock) -> None:
        """_git_publish_sync returns True when git operations succeed."""
        mock_subprocess.side_effect = [
            Mock(stdout=" M .beads/items.jsonl", returncode=0),
            Mock(stdout="", returncode=0),
            Mock(stdout="", returncode=0),
            Mock(stdout="", returncode=0),
        ]
        result = ExplicitSync._git_publish_sync()
        assert result is True

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_returns_false_on_push_failure(
        self, mock_subprocess: Mock,
    ) -> None:
        """_git_publish_sync returns False when git push fails."""
        mock_subprocess.side_effect = [
            Mock(stdout=" M .beads/items.jsonl", returncode=0),
            Mock(stdout="", returncode=0),
            Mock(stdout="", returncode=0),
            subprocess.CalledProcessError(1, "git push"),
        ]
        result = ExplicitSync._git_publish_sync()
        assert result is False

    @patch(_SUBPROCESS_RUN_PATH)
    def test_git_publish_sync_returns_false_on_timeout(
        self, mock_subprocess: Mock,
    ) -> None:
        """_git_publish_sync returns False on timeout."""
        mock_subprocess.side_effect = [
            subprocess.TimeoutExpired("git", 10),
        ]
        result = ExplicitSync._git_publish_sync()
        assert result is False

    @patch("pokepoke.beads.sync_strategy.ExplicitSync._git_publish_sync")
    @patch(_RUN_CLI_PATH)
    def test_sync_returns_failure_when_git_publish_fails(
        self, mock_run_cli: Mock, mock_git_pub: Mock,
    ) -> None:
        """sync() returns non-zero when br sync succeeds but git publish fails."""
        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        mock_git_pub.return_value = False
        strategy = ExplicitSync(backend=BR_CONFIG)

        result = strategy.sync()

        assert result.returncode == 1
        assert "git publish failed" in result.stderr
        mock_git_pub.assert_called_once()

    @patch("pokepoke.beads.sync_strategy.ExplicitSync._git_publish_sync")
    @patch(_RUN_CLI_PATH)
    def test_sync_returns_success_when_git_publish_succeeds(
        self, mock_run_cli: Mock, mock_git_pub: Mock,
    ) -> None:
        """sync() returns zero when both br sync and git publish succeed."""
        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        mock_git_pub.return_value = True
        strategy = ExplicitSync(backend=BR_CONFIG)

        result = strategy.sync()

        assert result.returncode == 0
        mock_git_pub.assert_called_once()


# ---------------------------------------------------------------------------
# Active sync strategy management
# ---------------------------------------------------------------------------


class TestActiveSyncStrategy:

    def test_default_strategy_is_daemon_sync(self) -> None:
        strategy = get_active_sync_strategy()
        assert isinstance(strategy, DaemonSync)

    def test_set_and_get_strategy(self) -> None:
        original = get_active_sync_strategy()
        try:
            explicit = ExplicitSync(backend=BR_CONFIG)
            set_active_sync_strategy(explicit)
            assert get_active_sync_strategy() is explicit
        finally:
            set_active_sync_strategy(original)

    def test_cannot_instantiate_abstract_base(self) -> None:
        with pytest.raises(TypeError):
            SyncStrategy()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Integration: set_active_backend updates sync strategy
# ---------------------------------------------------------------------------


class TestBackendSyncStrategyWiring:

    def test_set_backend_to_br_uses_explicit_sync(self) -> None:
        original_backend = get_active_backend()
        original_strategy = get_active_sync_strategy()
        try:
            set_active_backend(BR_CONFIG)
            strategy = get_active_sync_strategy()
            assert isinstance(strategy, ExplicitSync)
        finally:
            set_active_backend(original_backend)
            set_active_sync_strategy(original_strategy)

    def test_set_backend_to_bd_uses_daemon_sync(self) -> None:
        original_backend = get_active_backend()
        original_strategy = get_active_sync_strategy()
        try:
            set_active_backend(BR_CONFIG)
            set_active_backend(BD_CONFIG)
            strategy = get_active_sync_strategy()
            assert isinstance(strategy, DaemonSync)
        finally:
            set_active_backend(original_backend)
            set_active_sync_strategy(original_strategy)

    def test_custom_backend_defaults_to_daemon_sync(self) -> None:
        original_backend = get_active_backend()
        original_strategy = get_active_sync_strategy()
        try:
            custom = CLIBackendConfig(binary="custom-tool")
            set_active_backend(custom)
            strategy = get_active_sync_strategy()
            assert isinstance(strategy, DaemonSync)
        finally:
            set_active_backend(original_backend)
            set_active_sync_strategy(original_strategy)


# ---------------------------------------------------------------------------
# Integration: run_bd_sync_with_retry delegates to active strategy
# ---------------------------------------------------------------------------


class TestRunBdSyncDelegation:
    """Verify that beads_management.run_bd_sync_with_retry delegates."""

    @patch(_RUN_CLI_PATH)
    def test_delegates_to_daemon_sync_by_default(
        self, mock_run_cli: Mock,
    ) -> None:
        from pokepoke.beads.beads_management import run_bd_sync_with_retry

        mock_run_cli.return_value = Mock(returncode=0, stdout="", stderr="")
        original_strategy = get_active_sync_strategy()
        try:
            set_active_sync_strategy(DaemonSync(backend=BD_CONFIG))
            result = run_bd_sync_with_retry()
            assert result.returncode == 0
        finally:
            set_active_sync_strategy(original_strategy)

    def test_delegates_to_explicit_sync_when_active(self) -> None:
        from pokepoke.beads.beads_management import run_bd_sync_with_retry

        mock_strategy = Mock(spec=SyncStrategy)
        mock_strategy.sync.return_value = Mock(returncode=0, stdout="", stderr="")
        original = get_active_sync_strategy()
        try:
            set_active_sync_strategy(mock_strategy)
            run_bd_sync_with_retry(max_attempts=5, base_delay=2.0, timeout=99)
            mock_strategy.sync.assert_called_once_with(
                max_attempts=5, base_delay=2.0, timeout=99,
            )
        finally:
            set_active_sync_strategy(original)


# ---------------------------------------------------------------------------
# Backward compatibility: _is_transient_jsonl_sync_error importable
# from beads_management
# ---------------------------------------------------------------------------


class TestBackwardCompat:

    def test_jsonl_error_importable_from_beads_management(self) -> None:
        from pokepoke.beads.beads_management import _is_transient_jsonl_sync_error

        assert _is_transient_jsonl_sync_error("failed to replace jsonl file") is True
        assert _is_transient_jsonl_sync_error("random error") is False
