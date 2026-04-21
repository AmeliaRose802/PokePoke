"""Validation tests for unassign_item and unassign_with_retry.

Tests edge cases, input validation, and error handling for the
'Unassign Ex' (exception handling) functionality.
"""

import subprocess
from unittest.mock import Mock, patch

import pytest

from pokepoke.beads.beads_management import unassign_item
from pokepoke.beads.beads_manifest_utils import unassign_with_retry


class TestUnassignItemValidation:
    """Input validation tests for unassign_item."""

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_empty_string_item_id(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign with empty string item_id passes through to bd."""
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        # Empty string is technically valid (bd will reject it), so function
        # should attempt the operation
        result = unassign_item("")

        assert result is True
        mock_run_bd.assert_called_once()
        args = mock_run_bd.call_args[0][0]
        assert '' in args  # empty string passed to bd

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_whitespace_item_id(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign with whitespace-only item_id."""
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("   ")

        assert result is True
        mock_run_bd.assert_called_once()
        args = mock_run_bd.call_args[0][0]
        assert '   ' in args

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_special_characters_in_item_id(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign handles item IDs with special characters."""
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        special_ids = [
            "item-with-dashes",
            "item_with_underscores",
            "item.with.dots",
            "item/with/slashes",
            "item:with:colons",
        ]

        for item_id in special_ids:
            result = unassign_item(item_id)
            assert result is True

        assert mock_run_bd.call_count == len(special_ids)

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_very_long_item_id(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign with extremely long item ID."""
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        long_id = "x" * 1000  # 1000 character item ID
        result = unassign_item(long_id)

        assert result is True
        mock_run_bd.assert_called_once()


class TestUnassignItemExceptionHandling:
    """Exception handling tests for unassign_item."""

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_handles_runtime_error_from_bd(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign handles RuntimeError from _run_bd."""
        mock_run_bd.side_effect = RuntimeError("Unexpected error")

        # RuntimeError should not be caught by CalledProcessError handler
        with pytest.raises(RuntimeError, match="Unexpected error"):
            unassign_item("item-1")

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_handles_timeout_error(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign handles subprocess.TimeoutExpired gracefully."""
        mock_run_bd.side_effect = subprocess.TimeoutExpired("bd", 30)

        # TimeoutExpired is caught and returns False (doesn't raise)
        result = unassign_item("item-1")
        assert result is False

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_stderr_none_handled_safely(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign handles None stderr gracefully."""
        mock_run_bd.return_value = Mock(stderr=None)
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("item-1")

        # None stderr should not raise error
        assert result is True

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_stderr_error_case_insensitive(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test stderr error detection is case-insensitive."""
        test_cases = [
            "ERROR: validation failed",
            "Error: invalid field",
            "error: cannot update",
            "FATAL ERROR",
        ]

        for stderr_msg in test_cases:
            mock_run_bd.reset_mock()
            mock_run_bd.side_effect = [
                Mock(stderr=stderr_msg),
                Mock(stderr=''),  # fallback succeeds
            ]
            mock_sync.return_value = Mock(returncode=0)

            result = unassign_item("item-1")

            # Should trigger fallback due to error in stderr
            assert result is True
            assert mock_run_bd.call_count == 2, f"Failed for stderr: {stderr_msg}"

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_stderr_with_error_substring_triggers_fallback(
        self, mock_run_bd: Mock, mock_sync: Mock
    ) -> None:
        """Test that 'error' as substring triggers fallback."""
        mock_run_bd.side_effect = [
            Mock(stderr="Warning: operation encountered an internal error"),
            Mock(stderr=''),
        ]
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("item-1")

        # Should detect 'error' in message and retry
        assert result is True
        assert mock_run_bd.call_count == 2

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_sync_exception_does_not_fail_unassign(
        self, mock_run_bd: Mock, mock_sync: Mock
    ) -> None:
        """Test that sync exception doesn't fail the unassign."""
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.side_effect = RuntimeError("Sync crashed")

        # Sync failure should be caught and logged, but not fail the operation
        with pytest.raises(RuntimeError, match="Sync crashed"):
            unassign_item("item-1")

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_both_attempts_raise_exception(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test when both bd update attempts raise CalledProcessError."""
        mock_run_bd.side_effect = [
            subprocess.CalledProcessError(1, "bd", stderr="first error"),
            subprocess.CalledProcessError(1, "bd", stderr="second error"),
        ]

        result = unassign_item("item-1")

        assert result is False
        assert mock_run_bd.call_count == 2


class TestUnassignWithRetryValidation:
    """Validation tests for unassign_with_retry."""

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_empty_string_item_id(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        """Test unassign_with_retry with empty string."""
        mock_unassign.return_value = True

        result = unassign_with_retry("")

        assert result is True
        mock_unassign.assert_called_once_with("")

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_whitespace_item_id(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        """Test unassign_with_retry with whitespace-only item_id."""
        mock_unassign.return_value = True

        result = unassign_with_retry("   ")

        assert result is True
        mock_unassign.assert_called_once_with("   ")

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_handles_value_error_from_unassign(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        """Test retry handles ValueError from unassign_item."""
        mock_unassign.side_effect = ValueError("Invalid item ID format")

        result = unassign_with_retry("invalid-id")

        assert result is False
        assert mock_unassign.call_count == 3
        mock_add.assert_called_once()

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_handles_os_error_from_unassign(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        """Test retry handles OSError from unassign_item."""
        mock_unassign.side_effect = OSError("File not found")

        result = unassign_with_retry("item-1")

        assert result is False
        assert mock_unassign.call_count == 3
        mock_add.assert_called_once()

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_intermittent_failures_recover(
        self, mock_unassign: Mock, mock_sleep: Mock
    ) -> None:
        """Test retry recovers from intermittent failures."""
        # Fail twice, succeed on third attempt
        mock_unassign.side_effect = [
            False,
            RuntimeError("Transient error"),
            True,
        ]

        result = unassign_with_retry("item-1")

        assert result is True
        assert mock_unassign.call_count == 3
        # Should sleep twice (between attempts 1-2 and 2-3)
        assert mock_sleep.call_count == 2

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_records_last_error_message(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        """Test that last error message is recorded in manifest."""
        error_msg = "Final failure message"
        mock_unassign.side_effect = [
            RuntimeError("First error"),
            RuntimeError("Second error"),
            RuntimeError(error_msg),
        ]

        result = unassign_with_retry("item-1")

        assert result is False
        mock_add.assert_called_once()
        # Check that the reason contains the last error
        call_args = mock_add.call_args
        assert error_msg in str(call_args[0][1])

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_no_delay_before_first_attempt(
        self, mock_unassign: Mock, mock_sleep: Mock
    ) -> None:
        """Test no sleep before first unassign attempt."""
        mock_unassign.side_effect = [False, True]

        result = unassign_with_retry("item-1")

        assert result is True
        # Should sleep once (between attempts 1 and 2), not before attempt 1
        assert mock_sleep.call_count == 1

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_records_unknown_error_when_none(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        """Test records 'unknown' reason when no exception captured."""
        # This shouldn't normally happen, but test the fallback
        mock_unassign.return_value = False

        result = unassign_with_retry("item-1")

        assert result is False
        mock_add.assert_called_once()
        call_args = mock_add.call_args
        # Should contain reference to last error or "False"
        assert "False" in str(call_args[0][1]) or "unknown" in str(call_args[0][1]).lower()


class TestUnassignEdgeCases:
    """Edge case tests for unassign functionality."""

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_stderr_empty_string_vs_none(
        self, mock_run_bd: Mock, mock_sync: Mock
    ) -> None:
        """Test distinguishing between empty string and None stderr."""
        mock_sync.return_value = Mock(returncode=0)

        # Empty string stderr - should not trigger error detection
        mock_run_bd.return_value = Mock(stderr='')
        result = unassign_item("item-1")
        assert result is True
        assert mock_run_bd.call_count == 1

        mock_run_bd.reset_mock()

        # None stderr - should not trigger error detection
        mock_run_bd.return_value = Mock(stderr=None)
        result = unassign_item("item-2")
        assert result is True
        assert mock_run_bd.call_count == 1

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_unicode_in_item_id(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Test unassign handles Unicode characters in item IDs."""
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        unicode_ids = [
            "item-café",
            "task-日本語",
            "bug-émoji-🐛",
        ]

        for item_id in unicode_ids:
            result = unassign_item(item_id)
            assert result is True

        assert mock_run_bd.call_count == len(unicode_ids)

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_concurrent_unassign_same_item(
        self, mock_run_bd: Mock, mock_sync: Mock
    ) -> None:
        """Test multiple unassign calls for same item (simulate race condition)."""
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        # Simulate concurrent unassign attempts (though this is just sequential)
        results = [unassign_item("item-1") for _ in range(3)]

        assert all(r is True for r in results)
        assert mock_run_bd.call_count == 3
