"""Tests for pokepoke.utils.file_utils module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.utils.file_utils import replace_with_retry


class TestReplaceWithRetry:
    """Tests for replace_with_retry function."""

    def test_successful_replace_on_first_attempt(self, tmp_path: Path) -> None:
        """Replace succeeds immediately when no permission error."""
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("new content")
        dst.write_text("old content")

        replace_with_retry(src, dst)

        assert dst.read_text() == "new content"
        assert not src.exists()

    def test_successful_replace_creates_dst_if_missing(self, tmp_path: Path) -> None:
        """Replace works when destination doesn't exist yet."""
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("content")

        replace_with_retry(src, dst)

        assert dst.read_text() == "content"
        assert not src.exists()

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.utils.file_utils.os.replace")
    def test_retries_on_permission_error(
        self, mock_replace: patch, mock_sleep: patch
    ) -> None:
        """Retries when PermissionError is raised, then succeeds."""
        mock_replace.side_effect = [PermissionError, PermissionError, None]

        replace_with_retry(Path("src"), Path("dst"))

        assert mock_replace.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.utils.file_utils.os.replace")
    def test_raises_after_all_retries_exhausted(
        self, mock_replace: patch, mock_sleep: patch
    ) -> None:
        """Raises PermissionError when all retries are exhausted."""
        mock_replace.side_effect = PermissionError("locked")

        with pytest.raises(PermissionError, match="locked"):
            replace_with_retry(Path("src"), Path("dst"), retries=3)

        assert mock_replace.call_count == 3
        # Sleep called retries-1 times (not after the final failure)
        assert mock_sleep.call_count == 2

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.utils.file_utils.os.replace")
    def test_exponential_backoff_delays(
        self, mock_replace: patch, mock_sleep: patch
    ) -> None:
        """Verifies exponential backoff with jitter."""
        mock_replace.side_effect = [
            PermissionError,
            PermissionError,
            PermissionError,
            None,
        ]

        replace_with_retry(Path("src"), Path("dst"), delay=0.1)

        # With jitter enabled, delays should be in range [base*0.5, base*1.5]
        # Attempt 0: 0.1 * 2^0 = 0.1, jittered: [0.05, 0.15]
        # Attempt 1: 0.1 * 2^1 = 0.2, jittered: [0.1, 0.3]
        # Attempt 2: 0.1 * 2^2 = 0.4, jittered: [0.2, 0.6]
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert 0.05 <= delays[0] <= 0.15
        assert 0.1 <= delays[1] <= 0.3
        assert 0.2 <= delays[2] <= 0.6

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.utils.file_utils.os.replace")
    def test_single_retry(
        self, mock_replace: patch, mock_sleep: patch
    ) -> None:
        """With retries=1, no retry is attempted on failure."""
        mock_replace.side_effect = PermissionError("locked")

        with pytest.raises(PermissionError):
            replace_with_retry(Path("src"), Path("dst"), retries=1)

        assert mock_replace.call_count == 1
        mock_sleep.assert_not_called()

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.utils.file_utils.os.replace")
    def test_non_permission_error_not_retried(
        self, mock_replace: patch, mock_sleep: patch
    ) -> None:
        """Non-PermissionError exceptions propagate immediately."""
        mock_replace.side_effect = FileNotFoundError("missing")

        with pytest.raises(FileNotFoundError, match="missing"):
            replace_with_retry(Path("src"), Path("dst"))

        assert mock_replace.call_count == 1
        mock_sleep.assert_not_called()

    @patch("pokepoke.utils.file_utils.os.replace")
    def test_paths_converted_to_strings(self, mock_replace: patch) -> None:
        """Verifies Path objects are converted to strings for os.replace."""
        mock_replace.return_value = None
        src = Path("some/src")
        dst = Path("some/dst")

        replace_with_retry(src, dst)

        mock_replace.assert_called_once_with(str(src), str(dst))

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.utils.file_utils.os.replace")
    def test_default_parameters(
        self, mock_replace: patch, mock_sleep: patch
    ) -> None:
        """Default retries=5, delay=0.05 produce correct backoff with jitter."""
        mock_replace.side_effect = [PermissionError, None]

        replace_with_retry(Path("s"), Path("d"))

        # Default delay=0.05, first retry: 0.05 * 2^0 = 0.05, jittered: [0.025, 0.075]
        mock_sleep.assert_called_once()
        delay = mock_sleep.call_args[0][0]
        assert 0.025 <= delay <= 0.075

    @patch("pokepoke.utils.retry_utils.time.sleep")
    @patch("pokepoke.utils.file_utils.os.replace")
    def test_succeeds_on_last_retry(
        self, mock_replace: patch, mock_sleep: patch
    ) -> None:
        """Succeeds when the final retry attempt works."""
        errors = [PermissionError] * 4 + [None]
        mock_replace.side_effect = errors

        replace_with_retry(Path("s"), Path("d"), retries=5)

        assert mock_replace.call_count == 5
        assert mock_sleep.call_count == 4
