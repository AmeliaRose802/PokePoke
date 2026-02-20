"""Tests for repo_state_guard utilities."""

from unittest.mock import MagicMock, patch


from pokepoke import repo_state_guard as guard


class TestIsMainRepoClean:
    """Tests for dirty-state detection."""

    def test_returns_underlying_status(self):
        """Should surface non-beads file list from git helper."""
        with patch.object(guard, "verify_main_repo_clean", return_value=(True, "", [])) as mock_verify:
            clean, files = guard.is_main_repo_clean()
            assert clean is True
            assert files == []
            mock_verify.assert_called_once()

    def test_runtime_error_marks_dirty(self):
        """Runtime errors should be treated as dirty to fail-safe."""
        with patch.object(guard, "verify_main_repo_clean", side_effect=RuntimeError("boom")):
            clean, files = guard.is_main_repo_clean()
            assert clean is False
            assert files == ["boom"]


class TestCleanupLockActive:
    """Tests for cleanup lock detection."""

    def test_returns_false_when_lock_free(self):
        """If try_lock succeeds, the lock is not active."""
        mock_lock = MagicMock()
        with patch.object(guard, "try_lock", return_value=mock_lock):
            assert guard.cleanup_lock_active() is False
            mock_lock.release.assert_called_once()

    def test_returns_true_when_lock_busy(self):
        """If try_lock fails, lock is considered active."""
        with patch.object(guard, "try_lock", return_value=None):
            assert guard.cleanup_lock_active() is True


class TestWaitForMainRepoClean:
    """Tests for the wait loop."""

    def test_returns_immediately_when_clean(self):
        """If repo clean and lock free, should return True."""
        with patch.object(guard, "is_main_repo_clean", return_value=(True, [])), \
             patch.object(guard, "cleanup_lock_active", return_value=False):
            assert guard.wait_for_main_repo_clean(timeout=0.1, poll_interval=0.01) is True

    def test_waits_until_repo_clean(self):
        """Should poll until clean state is reached."""
        states = [
            (False, [" M file.py"]),
            (False, [" M file.py"]),
            (True, []),
        ]
        with patch.object(guard, "is_main_repo_clean", side_effect=states), \
             patch.object(guard, "cleanup_lock_active", return_value=False):
            result = guard.wait_for_main_repo_clean(timeout=0.5, poll_interval=0.01)
            assert result is True

    def test_waits_until_lock_released(self):
        """Should stay in loop while cleanup lock is active."""
        lock_states = [True, True, False]
        with patch.object(guard, "is_main_repo_clean", return_value=(True, [])), \
             patch.object(guard, "cleanup_lock_active", side_effect=lock_states) as mock_lock:
            assert guard.wait_for_main_repo_clean(timeout=0.5, poll_interval=0.01) is True
            assert mock_lock.call_count == len(lock_states)

    def test_times_out_if_still_dirty(self):
        """Return False when timeout expires."""
        events = []

        def _log(msg: str) -> None:
            events.append(msg)

        with patch.object(guard, "is_main_repo_clean", return_value=(False, [" M file.py"])), \
             patch.object(guard, "cleanup_lock_active", return_value=False):
            result = guard.wait_for_main_repo_clean(timeout=0.05, poll_interval=0.01, log_fn=_log)
            assert result is False
            assert any("Timed out" in msg for msg in events)
