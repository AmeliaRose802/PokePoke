"""Tests for preflight_log_utils module."""

from unittest.mock import MagicMock

from pokepoke.preflight_log_utils import (
    format_preflight_errors,
    get_preflight_fail_count,
    reset_preflight_rate_limit,
    should_log_preflight_warning,
)


class TestFormatPreflightErrors:
    """Tests for format_preflight_errors."""

    def test_single_error(self):
        err = MagicMock(check_name="disk_space", message="Low disk space")
        assert format_preflight_errors([err]) == "disk_space: Low disk space"

    def test_multiple_errors(self):
        e1 = MagicMock(check_name="disk_space", message="Low disk")
        e2 = MagicMock(check_name="git_locks", message="Stale lock")
        assert format_preflight_errors([e1, e2]) == "disk_space: Low disk; git_locks: Stale lock"

    def test_empty_errors(self):
        assert format_preflight_errors([]) == ""


class TestShouldLogPreflightWarning:
    """Tests for should_log_preflight_warning and rate-limiting."""

    def setup_method(self):
        reset_preflight_rate_limit()

    def teardown_method(self):
        reset_preflight_rate_limit()

    def test_first_occurrence_always_logged(self):
        assert should_log_preflight_warning("disk_space: Low disk") is True

    def test_second_occurrence_suppressed(self):
        should_log_preflight_warning("disk_space: Low disk")
        assert should_log_preflight_warning("disk_space: Low disk") is False

    def test_different_signature_resets(self):
        should_log_preflight_warning("disk_space: Low disk")
        assert should_log_preflight_warning("git_locks: Stale lock") is True

    def test_50th_occurrence_logged(self):
        sig = "disk_space: Low disk"
        should_log_preflight_warning(sig)  # count=1 -> True
        for _ in range(48):
            should_log_preflight_warning(sig)  # counts 2-49 -> False
        assert should_log_preflight_warning(sig) is True  # count=50 -> True

    def test_reset_clears_state(self):
        should_log_preflight_warning("disk_space: Low disk")
        should_log_preflight_warning("disk_space: Low disk")
        reset_preflight_rate_limit()
        assert should_log_preflight_warning("disk_space: Low disk") is True


class TestGetPreflightFailCount:
    """Tests for get_preflight_fail_count."""

    def setup_method(self):
        reset_preflight_rate_limit()

    def teardown_method(self):
        reset_preflight_rate_limit()

    def test_initial_count_is_zero(self):
        assert get_preflight_fail_count() == 0

    def test_count_increments(self):
        should_log_preflight_warning("err")
        assert get_preflight_fail_count() == 1
        should_log_preflight_warning("err")
        assert get_preflight_fail_count() == 2
