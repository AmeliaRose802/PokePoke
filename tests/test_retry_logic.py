"""Tests for retry logic with exponential backoff."""

import time
from unittest.mock import Mock, patch, MagicMock
import pytest

from pokepoke.copilot import (
    is_rate_limited,
    is_transient_error,
    calculate_backoff_delay,
    invoke_copilot_cli
)
from pokepoke.types import BeadsWorkItem, CopilotResult, RetryConfig


class TestRateLimitDetection:
    """Tests for rate limit detection."""
    
    def test_detects_http_429(self):
        """Should detect HTTP 429 status code."""
        stderr = "Error: HTTP 429 - Too Many Requests"
        assert is_rate_limited(stderr, 1) is True
    
    def test_detects_rate_limit_text(self):
        """Should detect 'rate limit' in error message."""
        stderr = "You have been rate limited. Please try again later."
        assert is_rate_limited(stderr, 1) is True
    
    def test_detects_too_many_requests(self):
        """Should detect 'too many requests' phrase."""
        stderr = "Error: Too many requests to the API"
        assert is_rate_limited(stderr, 1) is True
    
    def test_detects_throttle(self):
        """Should detect 'throttle' in error message."""
        stderr = "Request throttled due to excessive usage"
        assert is_rate_limited(stderr, 1) is True
    
    def test_detects_quota_exceeded(self):
        """Should detect 'quota exceeded' phrase."""
        stderr = "API quota exceeded for this period"
        assert is_rate_limited(stderr, 1) is True
    
    def test_detects_try_again_later(self):
        """Should detect 'try again later' phrase."""
        stderr = "Service unavailable. Please try again later."
        assert is_rate_limited(stderr, 1) is True
    
    def test_case_insensitive(self):
        """Should detect rate limiting regardless of case."""
        stderr = "ERROR: RATE LIMIT EXCEEDED"
        assert is_rate_limited(stderr, 1) is True
    
    def test_no_false_positive(self):
        """Should not detect rate limiting in normal errors."""
        stderr = "Error: Invalid authentication token"
        assert is_rate_limited(stderr, 1) is False
    
    def test_empty_stderr(self):
        """Should handle empty stderr gracefully."""
        assert is_rate_limited("", 0) is False
        assert is_rate_limited(None, 0) is False


class TestTransientErrorDetection:
    """Tests for transient error detection."""
    
    def test_detects_timeout(self):
        """Should detect timeout errors."""
        stderr = "Error: Request timed out after 30s"
        assert is_transient_error(stderr, 1) is True
    
    def test_detects_connection_error(self):
        """Should detect connection errors."""
        stderr = "Connection refused by remote server"
        assert is_transient_error(stderr, 1) is True
    
    def test_detects_network_error(self):
        """Should detect network errors."""
        stderr = "Network error: Unable to reach host"
        assert is_transient_error(stderr, 1) is True
    
    def test_detects_http_503(self):
        """Should detect HTTP 503 Service Unavailable."""
        stderr = "HTTP 503: Service Temporarily Unavailable"
        assert is_transient_error(stderr, 1) is True
    
    def test_detects_http_502(self):
        """Should detect HTTP 502 Bad Gateway."""
        stderr = "502 Bad Gateway"
        assert is_transient_error(stderr, 1) is True
    
    def test_detects_http_504(self):
        """Should detect HTTP 504 Gateway Timeout."""
        stderr = "Error 504: Gateway Timeout"
        assert is_transient_error(stderr, 1) is True
    
    def test_case_insensitive(self):
        """Should detect transient errors regardless of case."""
        stderr = "CONNECTION TIMEOUT"
        assert is_transient_error(stderr, 1) is True
    
    def test_no_false_positive(self):
        """Should not detect transient errors in permanent failures."""
        stderr = "Error: Invalid API key"
        assert is_transient_error(stderr, 1) is False
    
    def test_empty_stderr(self):
        """Should handle empty stderr gracefully."""
        assert is_transient_error("", 0) is False
        assert is_transient_error(None, 0) is False


class TestBackoffCalculation:
    """Tests for exponential backoff delay calculation."""
    
    def test_initial_delay(self):
        """Should return initial delay for first retry."""
        config = RetryConfig(initial_delay=1.0, backoff_factor=2.0, jitter=False)
        delay = calculate_backoff_delay(0, config)
        assert delay == 1.0
    
    def test_exponential_growth(self):
        """Should double delay with each attempt."""
        config = RetryConfig(initial_delay=1.0, backoff_factor=2.0, jitter=False)
        assert calculate_backoff_delay(0, config) == 1.0
        assert calculate_backoff_delay(1, config) == 2.0
        assert calculate_backoff_delay(2, config) == 4.0
        assert calculate_backoff_delay(3, config) == 8.0
    
    def test_max_delay_cap(self):
        """Should cap delay at max_delay."""
        config = RetryConfig(initial_delay=1.0, backoff_factor=2.0, max_delay=5.0, jitter=False)
        assert calculate_backoff_delay(10, config) == 5.0  # Would be 1024 without cap
    
    def test_custom_backoff_factor(self):
        """Should support custom backoff factors."""
        config = RetryConfig(initial_delay=1.0, backoff_factor=3.0, jitter=False)
        assert calculate_backoff_delay(0, config) == 1.0
        assert calculate_backoff_delay(1, config) == 3.0
        assert calculate_backoff_delay(2, config) == 9.0
    
    def test_jitter_adds_randomness(self):
        """Should add jitter to prevent thundering herd."""
        config = RetryConfig(initial_delay=10.0, backoff_factor=2.0, jitter=True)
        
        # With jitter, delays should vary within ±25% of base delay
        delays = [calculate_backoff_delay(1, config) for _ in range(100)]
        
        # All delays should be within range (20 * 0.75 to 20 * 1.25)
        assert all(15.0 <= d <= 25.0 for d in delays)
        
        # Delays should not all be the same (very unlikely with 100 samples)
        assert len(set(delays)) > 1
    
    def test_jitter_minimum_delay(self):
        """Should enforce minimum delay of 0.1s even with jitter."""
        config = RetryConfig(initial_delay=0.1, backoff_factor=1.0, jitter=True)
        delay = calculate_backoff_delay(0, config)
        assert delay >= 0.1


class TestInvokeCopilotWithRetry:
    """Tests for invoke_copilot_cli with retry logic."""
    
    @pytest.fixture
    def work_item(self):
        """Create a test work item."""
        return BeadsWorkItem(
            id="test-123",
            title="Test work item",
            status="open",
            priority=1,
            issue_type="bug",
            description="Test description"
        )
    
    @pytest.fixture
    def mock_process(self):
        """Create a mock process object."""
        process = MagicMock()
        process.stdout = iter([])
        process.stderr = MagicMock()
        process.stderr.read.return_value = ""
        process.returncode = 0
        process.wait = MagicMock()
        return process
    
    def test_success_first_attempt(self, work_item, mock_process):
        """Should succeed on first attempt without retries."""
        mock_process.returncode = 0
        
        with patch('subprocess.Popen', return_value=mock_process):
            result = invoke_copilot_cli(work_item, retry_config=RetryConfig(max_retries=3))
        
        assert result.success is True
        assert result.attempt_count == 1
        assert result.is_rate_limited is False
    
    def test_rate_limit_retry_success(self, work_item, mock_process):
        """Should retry on rate limit and eventually succeed."""
        # First call: rate limited, second call: success
        call_count = 0
        
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            process = MagicMock()
            process.stdout = iter([])
            process.stderr = MagicMock()
            process.wait = MagicMock()
            
            if call_count == 1:
                process.returncode = 1
                process.stderr.read.return_value = "HTTP 429: Rate Limit Exceeded"
            else:
                process.returncode = 0
                process.stderr.read.return_value = ""
            
            return process
        
        with patch('subprocess.Popen', side_effect=side_effect):
            with patch('time.sleep'):  # Mock sleep to speed up test
                result = invoke_copilot_cli(work_item, retry_config=RetryConfig(max_retries=3))
        
        assert result.success is True
        assert result.attempt_count == 2
    
    def test_transient_error_retry_success(self, work_item):
        """Should retry on transient errors and eventually succeed."""
        call_count = 0
        
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            process = MagicMock()
            process.stdout = iter([])
            process.stderr = MagicMock()
            process.wait = MagicMock()
            
            if call_count == 1:
                process.returncode = 1
                process.stderr.read.return_value = "Connection timeout"
            else:
                process.returncode = 0
                process.stderr.read.return_value = ""
            
            return process
        
        with patch('subprocess.Popen', side_effect=side_effect):
            with patch('time.sleep'):
                result = invoke_copilot_cli(work_item, retry_config=RetryConfig(max_retries=3))
        
        assert result.success is True
        assert result.attempt_count == 2
    
    def test_permanent_error_no_retry(self, work_item):
        """Should not retry on permanent errors."""
        process = MagicMock()
        process.stdout = iter([])
        process.stderr = MagicMock()
        process.stderr.read.return_value = "Invalid API key"
        process.returncode = 1
        process.wait = MagicMock()
        
        with patch('subprocess.Popen', return_value=process) as mock_popen:
            result = invoke_copilot_cli(work_item, retry_config=RetryConfig(max_retries=3))
        
        # Should only be called once (no retries)
        assert mock_popen.call_count == 1
        assert result.success is False
        assert result.attempt_count == 1
        assert result.is_rate_limited is False
    
    def test_exhausts_retries(self, work_item):
        """Should fail after exhausting all retries."""
        process = MagicMock()
        process.stdout = iter([])
        process.stderr = MagicMock()
        process.stderr.read.return_value = "HTTP 429: Rate Limit"
        process.returncode = 1
        process.wait = MagicMock()
        
        with patch('subprocess.Popen', return_value=process) as mock_popen:
            with patch('time.sleep'):
                result = invoke_copilot_cli(work_item, retry_config=RetryConfig(max_retries=2))
        
        # Should try initial + 2 retries = 3 total
        assert mock_popen.call_count == 3
        assert result.success is False
        assert result.attempt_count == 3
        assert result.is_rate_limited is True
    
    def test_applies_backoff_delay(self, work_item):
        """Should apply exponential backoff between retries."""
        process = MagicMock()
        process.stdout = iter([])
        process.stderr = MagicMock()
        process.stderr.read.return_value = "HTTP 429"
        process.returncode = 1
        process.wait = MagicMock()
        
        sleep_calls = []
        
        def mock_sleep(seconds):
            sleep_calls.append(seconds)
        
        with patch('subprocess.Popen', return_value=process):
            with patch('time.sleep', side_effect=mock_sleep):
                result = invoke_copilot_cli(
                    work_item,
                    retry_config=RetryConfig(
                        max_retries=2,
                        initial_delay=1.0,
                        backoff_factor=2.0,
                        jitter=False
                    )
                )
        
        # Should have 2 sleep calls (one before each retry)
        assert len(sleep_calls) == 2
        # First retry: 1.0s, second retry: 2.0s
        assert sleep_calls[0] == 1.0
        assert sleep_calls[1] == 2.0
    
    def test_timeout_is_not_retried(self, work_item):
        """Should NOT retry on timeout exceptions - process is stuck."""
        call_count = 0
        
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            
            process = MagicMock()
            process.stdout = iter([])
            process.stderr = MagicMock()
            
            # First call times out - should NOT retry
            from subprocess import TimeoutExpired
            process.wait.side_effect = TimeoutExpired(cmd="test", timeout=300)
            
            return process
        
        with patch('subprocess.Popen', side_effect=side_effect):
            with patch('time.sleep'):
                result = invoke_copilot_cli(work_item, retry_config=RetryConfig(max_retries=3))
        
        # Should fail immediately on timeout, NOT retry
        assert result.success is False
        assert result.attempt_count == 1
        assert "timed out" in result.error.lower()
        # Should only have been called once (no retries)
        assert call_count == 1


class TestRetryConfigDefaults:
    """Tests for RetryConfig default values."""
    
    def test_default_values(self):
        """Should use sensible defaults."""
        config = RetryConfig()
        assert config.max_retries == 3
        assert config.initial_delay == 1.0
        assert config.max_delay == 60.0
        assert config.backoff_factor == 2.0
        assert config.jitter is True
    
    def test_custom_values(self):
        """Should allow custom configuration."""
        config = RetryConfig(
            max_retries=5,
            initial_delay=2.0,
            max_delay=120.0,
            backoff_factor=3.0,
            jitter=False
        )
        assert config.max_retries == 5
        assert config.initial_delay == 2.0
        assert config.max_delay == 120.0
        assert config.backoff_factor == 3.0
        assert config.jitter is False
