"""Tests for retry utilities with jitter support."""
from unittest.mock import patch

import pytest

from pokepoke.types import RetryConfig
from pokepoke.utils.retry_utils import calculate_backoff_delay, sleep_with_backoff


class TestCalculateBackoffDelay:
    """Test backoff delay calculation with jitter."""

    def test_base_exponential_backoff_no_jitter(self):
        """Test exponential backoff without jitter."""
        config = RetryConfig(
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=60.0,
            jitter=False,
        )

        # Attempt 0: 1.0 * 2^0 = 1.0
        assert calculate_backoff_delay(0, config) == 1.0

        # Attempt 1: 1.0 * 2^1 = 2.0
        assert calculate_backoff_delay(1, config) == 2.0

        # Attempt 2: 1.0 * 2^2 = 4.0
        assert calculate_backoff_delay(2, config) == 4.0

        # Attempt 3: 1.0 * 2^3 = 8.0
        assert calculate_backoff_delay(3, config) == 8.0

    def test_exponential_backoff_with_jitter(self):
        """Test that jitter creates variation in delays."""
        config = RetryConfig(
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=60.0,
            jitter=True,
        )

        # Generate multiple delays for same attempt
        delays = [calculate_backoff_delay(2, config) for _ in range(100)]

        # Base delay for attempt 2: 1.0 * 2^2 = 4.0
        # With jitter: 4.0 * [0.5, 1.5] = [2.0, 6.0]
        base_delay = 4.0
        min_expected = base_delay * 0.5
        max_expected = base_delay * 1.5

        # All delays should be within jitter range
        assert all(min_expected <= d <= max_expected for d in delays)

        # There should be variation (not all identical)
        assert len(set(delays)) > 1

    def test_max_delay_cap_without_jitter(self):
        """Test that delays are capped at max_delay before jitter."""
        config = RetryConfig(
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=5.0,
            jitter=False,
        )

        # Attempt 10: would be 1024.0 but capped at 5.0
        assert calculate_backoff_delay(10, config) == 5.0

    def test_max_delay_cap_with_jitter(self):
        """Test that delays are capped at max_delay BEFORE jitter is applied."""
        config = RetryConfig(
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=5.0,
            jitter=True,
        )

        # Attempt 10: would be 1024.0 but capped at 5.0, then jitter applied
        # With jitter: 5.0 * [0.5, 1.5] = [2.5, 7.5]
        delays = [calculate_backoff_delay(10, config) for _ in range(100)]
        assert all(2.5 <= d <= 7.5 for d in delays)

    def test_custom_backoff_factor(self):
        """Test custom backoff factors."""
        config = RetryConfig(
            initial_delay=2.0,
            backoff_factor=3.0,
            max_delay=100.0,
            jitter=False,
        )

        # Attempt 0: 2.0 * 3^0 = 2.0
        assert calculate_backoff_delay(0, config) == 2.0

        # Attempt 1: 2.0 * 3^1 = 6.0
        assert calculate_backoff_delay(1, config) == 6.0

        # Attempt 2: 2.0 * 3^2 = 18.0
        assert calculate_backoff_delay(2, config) == 18.0

    def test_linear_backoff(self):
        """Test linear backoff mode: initial_delay * (attempt + 1)."""
        config = RetryConfig(
            initial_delay=1.0,
            max_delay=100.0,
            jitter=False,
            backoff_mode="linear",
        )

        # Attempt 0: 1.0 * (0 + 1) = 1.0
        assert calculate_backoff_delay(0, config) == 1.0

        # Attempt 1: 1.0 * (1 + 1) = 2.0
        assert calculate_backoff_delay(1, config) == 2.0

        # Attempt 2: 1.0 * (2 + 1) = 3.0
        assert calculate_backoff_delay(2, config) == 3.0

        # Attempt 4: 1.0 * (4 + 1) = 5.0
        assert calculate_backoff_delay(4, config) == 5.0

    def test_linear_backoff_with_custom_initial_delay(self):
        """Test linear backoff with non-default initial delay."""
        config = RetryConfig(
            initial_delay=0.05,
            max_delay=100.0,
            jitter=False,
            backoff_mode="linear",
        )

        # Matches original manifest_utils behavior: delay * (attempt + 1)
        assert calculate_backoff_delay(0, config) == pytest.approx(0.05)
        assert calculate_backoff_delay(1, config) == pytest.approx(0.10)
        assert calculate_backoff_delay(2, config) == pytest.approx(0.15)
        assert calculate_backoff_delay(3, config) == pytest.approx(0.20)
        assert calculate_backoff_delay(4, config) == pytest.approx(0.25)

    def test_linear_backoff_respects_max_delay(self):
        """Test that linear backoff is capped at max_delay."""
        config = RetryConfig(
            initial_delay=5.0,
            max_delay=10.0,
            jitter=False,
            backoff_mode="linear",
        )

        # Attempt 0: 5.0 * 1 = 5.0
        assert calculate_backoff_delay(0, config) == 5.0

        # Attempt 1: 5.0 * 2 = 10.0 (at cap)
        assert calculate_backoff_delay(1, config) == 10.0

        # Attempt 2: 5.0 * 3 = 15.0 → capped at 10.0
        assert calculate_backoff_delay(2, config) == 10.0

    def test_linear_backoff_with_jitter(self):
        """Test linear backoff with jitter applied."""
        config = RetryConfig(
            initial_delay=2.0,
            max_delay=100.0,
            jitter=True,
            backoff_mode="linear",
        )

        # Attempt 2: base = 2.0 * 3 = 6.0, jitter range [3.0, 9.0]
        delays = [calculate_backoff_delay(2, config) for _ in range(100)]
        assert all(3.0 <= d <= 9.0 for d in delays)
        assert len(set(delays)) > 1


class TestSleepWithBackoff:
    """Test the sleep_with_backoff function."""

    @patch('pokepoke.utils.retry_utils.time.sleep')
    def test_sleep_called_with_correct_delay(self, mock_sleep):
        """Test that time.sleep is called with calculated delay."""
        config = RetryConfig(
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=60.0,
            jitter=False,
        )

        actual_delay = sleep_with_backoff(2, config, 'test operation')

        # Attempt 2: 1.0 * 2^2 = 4.0
        assert actual_delay == 4.0
        mock_sleep.assert_called_once_with(4.0)

    @patch('pokepoke.utils.retry_utils.time.sleep')
    def test_sleep_with_jitter(self, mock_sleep):
        """Test that sleep is called with jittered delay."""
        config = RetryConfig(
            initial_delay=1.0,
            backoff_factor=2.0,
            max_delay=60.0,
            jitter=True,
        )

        actual_delay = sleep_with_backoff(1, config, 'test operation')

        # Base delay for attempt 1: 1.0 * 2^1 = 2.0
        # With jitter: 2.0 * [0.5, 1.5] = [1.0, 3.0]
        assert 1.0 <= actual_delay <= 3.0
        mock_sleep.assert_called_once()
        sleep_arg = mock_sleep.call_args[0][0]
        assert 1.0 <= sleep_arg <= 3.0

    @patch('pokepoke.utils.retry_utils.time.sleep')
    def test_sleep_without_context(self, mock_sleep):
        """Test sleep_with_backoff without context string."""
        config = RetryConfig(
            initial_delay=0.5,
            backoff_factor=2.0,
            max_delay=60.0,
            jitter=False,
        )

        actual_delay = sleep_with_backoff(0, config)

        # Attempt 0: 0.5 * 2^0 = 0.5
        assert actual_delay == 0.5
        mock_sleep.assert_called_once_with(0.5)


class TestJitterDistribution:
    """Test that jitter produces reasonable distribution."""

    def test_jitter_distribution_is_uniform(self):
        """Test that jitter produces uniform distribution in expected range."""
        config = RetryConfig(
            initial_delay=10.0,
            backoff_factor=1.0,
            max_delay=100.0,
            jitter=True,
        )

        # Generate many samples
        delays = [calculate_backoff_delay(0, config) for _ in range(1000)]

        # Base delay: 10.0
        # Jitter range: [5.0, 15.0]
        min_delay = min(delays)
        max_delay = max(delays)

        # Min should be close to 5.0, max close to 15.0
        assert 5.0 <= min_delay < 6.0
        assert 14.0 < max_delay <= 15.0

        # Mean should be close to 10.0
        mean_delay = sum(delays) / len(delays)
        assert 9.5 <= mean_delay <= 10.5


class TestRetryConfigIntegration:
    """Test that RetryConfig fields are properly consumed."""

    def test_all_config_fields_respected(self):
        """Test that all RetryConfig fields are used correctly."""
        config = RetryConfig(
            max_retries=5,
            initial_delay=2.0,
            backoff_factor=3.0,
            max_delay=50.0,
            jitter=False,
        )

        # Test initial_delay
        assert calculate_backoff_delay(0, config) == 2.0

        # Test backoff_factor
        assert calculate_backoff_delay(1, config) == 6.0  # 2.0 * 3^1
        assert calculate_backoff_delay(2, config) == 18.0  # 2.0 * 3^2

        # Test max_delay cap
        assert calculate_backoff_delay(10, config) == 50.0  # Would be 118098 but capped

    def test_jitter_flag_toggles_randomness(self):
        """Test that jitter flag actually controls randomness."""
        # Without jitter - deterministic
        config_no_jitter = RetryConfig(
            initial_delay=5.0,
            backoff_factor=2.0,
            max_delay=100.0,
            jitter=False,
        )
        delays_no_jitter = [calculate_backoff_delay(1, config_no_jitter) for _ in range(10)]
        assert len(set(delays_no_jitter)) == 1  # All identical

        # With jitter - random
        config_with_jitter = RetryConfig(
            initial_delay=5.0,
            backoff_factor=2.0,
            max_delay=100.0,
            jitter=True,
        )
        delays_with_jitter = [calculate_backoff_delay(1, config_with_jitter) for _ in range(100)]
        assert len(set(delays_with_jitter)) > 1  # Has variation
