"""Tests for copilot.py module to increase coverage."""

import pytest
import subprocess
import tempfile
import os
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path

from pokepoke.copilot import (
    get_allowed_directories,
    build_prompt_from_template,
    build_prompt,
    is_rate_limited,
    is_transient_error,
    calculate_backoff_delay,
    invoke_copilot_cli
)
from pokepoke.types import BeadsWorkItem, CopilotResult, RetryConfig


@pytest.fixture
def sample_work_item():
    """Create a sample work item for testing."""
    return BeadsWorkItem(
        id="test-123",
        title="Test work item",
        description="Test description",
        status="in_progress",
        priority=1,
        issue_type="task",
        labels=["testing", "coverage"]
    )


@pytest.fixture
def sample_work_item_no_labels():
    """Create a work item without labels."""
    return BeadsWorkItem(
        id="test-456",
        title="No labels item",
        description="Item without labels",
        status="in_progress",
        priority=2,
        issue_type="bug",
        labels=None
    )


class TestGetAllowedDirectories:
    """Tests for get_allowed_directories function."""
    
    def test_get_allowed_directories_success(self):
        """Test successful retrieval of allowed directories."""
        mock_result = MagicMock()
        mock_result.stdout = "/repo/.git\n"
        
        with patch('subprocess.run', return_value=mock_result):
            with patch('os.getcwd', return_value='/repo/worktree'):
                dirs = get_allowed_directories()
                
                assert '/repo/worktree' in dirs
                assert len(dirs) >= 1
    
    def test_get_allowed_directories_git_failure(self):
        """Test handling of git command failure (line 35-38)."""
        # Simulate git command failure
        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'git')):
            with patch('os.getcwd', return_value='/current/dir'):
                dirs = get_allowed_directories()
                
                # Should still return current directory
                assert '/current/dir' in dirs
                assert len(dirs) == 1
    
    def test_get_allowed_directories_generic_exception(self):
        """Test handling of generic exception (line 38)."""
        # Simulate generic exception
        with patch('subprocess.run', side_effect=Exception("Unexpected error")):
            with patch('os.getcwd', return_value='/current/dir'):
                dirs = get_allowed_directories()
                
                # Should still return current directory
                assert '/current/dir' in dirs
                assert len(dirs) == 1


class TestBuildPromptFromTemplate:
    """Tests for build_prompt_from_template function."""
    
    def test_build_prompt_from_template(self, sample_work_item):
        """Test building prompt from template."""
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Rendered prompt"
        
        with patch('pokepoke.copilot.PromptService', return_value=mock_service):
            with patch('pokepoke.copilot.get_allowed_directories', return_value=['/repo']):
                prompt = build_prompt_from_template(sample_work_item, "test-template")
                
                assert prompt == "Rendered prompt"
                mock_service.load_and_render.assert_called_once()
    
    def test_build_prompt_from_template_no_labels(self, sample_work_item_no_labels):
        """Test building prompt when work item has no labels."""
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Rendered prompt"
        
        with patch('pokepoke.copilot.PromptService', return_value=mock_service):
            with patch('pokepoke.copilot.get_allowed_directories', return_value=['/repo']):
                prompt = build_prompt_from_template(sample_work_item_no_labels)
                
                # Check that None is passed for labels
                call_args = mock_service.load_and_render.call_args
                variables = call_args[0][1]
                assert variables['labels'] is None


class TestBuildPrompt:
    """Tests for build_prompt function."""
    
    def test_build_prompt_with_labels(self, sample_work_item):
        """Test building prompt with labels."""
        prompt = build_prompt(sample_work_item)
        
        assert "test-123" in prompt
        assert "Test work item" in prompt
        assert "Test description" in prompt
        assert "testing, coverage" in prompt
    
    def test_build_prompt_without_labels(self, sample_work_item_no_labels):
        """Test building prompt without labels."""
        prompt = build_prompt(sample_work_item_no_labels)
        
        assert "test-456" in prompt
        assert "No labels item" in prompt
        # Should not include labels section
        assert "Labels:" not in prompt


class TestIsRateLimited:
    """Tests for is_rate_limited function."""
    
    def test_rate_limited_429(self):
        """Test detection of 429 rate limit."""
        assert is_rate_limited("Error 429 Too Many Requests", 1)
    
    def test_rate_limited_text(self):
        """Test detection of rate limit text."""
        assert is_rate_limited("API rate limit exceeded", 1)
        assert is_rate_limited("Too many requests, please try again later", 1)
        assert is_rate_limited("Request throttled due to quota exceeded", 1)
    
    def test_not_rate_limited(self):
        """Test non-rate-limit errors."""
        assert not is_rate_limited("Authentication failed", 1)
        assert not is_rate_limited("File not found", 1)
    
    def test_rate_limited_empty_stderr(self):
        """Test empty stderr returns False (line 86-87)."""
        assert not is_rate_limited("", 1)
        assert not is_rate_limited(None, 1)


class TestIsTransientError:
    """Tests for is_transient_error function."""
    
    def test_transient_timeout(self):
        """Test detection of timeout errors."""
        assert is_transient_error("Connection timed out", 1)
        assert is_transient_error("Request timeout occurred", 1)
    
    def test_transient_network(self):
        """Test detection of network errors."""
        assert is_transient_error("Network connection failed", 1)
        assert is_transient_error("Temporary network issue", 1)
    
    def test_transient_http_codes(self):
        """Test detection of transient HTTP codes."""
        assert is_transient_error("HTTP 503 Service Unavailable", 1)
        assert is_transient_error("Error 502 Bad Gateway", 1)
        assert is_transient_error("Gateway timeout 504", 1)
    
    def test_not_transient(self):
        """Test non-transient errors."""
        assert not is_transient_error("Permission denied", 1)
        assert not is_transient_error("Invalid syntax", 1)
    
    def test_transient_empty_stderr(self):
        """Test empty stderr returns False (line 88-89)."""
        assert not is_transient_error("", 1)
        assert not is_transient_error(None, 1)


class TestCalculateBackoffDelay:
    """Tests for calculate_backoff_delay function."""
    
    def test_backoff_basic(self):
        """Test basic exponential backoff."""
        config = RetryConfig(
            max_retries=3,
            initial_delay=1.0,
            max_delay=10.0,
            backoff_factor=2.0,
            jitter=False
        )
        
        # Attempt 0: 1.0 * (2.0 ^ 0) = 1.0
        assert calculate_backoff_delay(0, config) == 1.0
        
        # Attempt 1: 1.0 * (2.0 ^ 1) = 2.0
        assert calculate_backoff_delay(1, config) == 2.0
        
        # Attempt 2: 1.0 * (2.0 ^ 2) = 4.0
        assert calculate_backoff_delay(2, config) == 4.0
    
    def test_backoff_max_delay_cap(self):
        """Test that delay is capped at max_delay."""
        config = RetryConfig(
            max_retries=5,
            initial_delay=1.0,
            max_delay=5.0,
            backoff_factor=2.0,
            jitter=False
        )
        
        # Attempt 5 would be 32.0, but should be capped at 5.0
        assert calculate_backoff_delay(5, config) == 5.0
    
    def test_backoff_with_jitter(self):
        """Test backoff with jitter."""
        config = RetryConfig(
            max_retries=3,
            initial_delay=4.0,
            max_delay=10.0,
            backoff_factor=2.0,
            jitter=True
        )
        
        # With jitter, delay should be within ±25% of base delay
        # Attempt 0: base = 4.0, range = [3.0, 5.0]
        delay = calculate_backoff_delay(0, config)
        assert 3.0 <= delay <= 5.0
        
        # Multiple calls should produce different values (jitter randomness)
        delays = [calculate_backoff_delay(0, config) for _ in range(10)]
        assert len(set(delays)) > 1, "Jitter should produce varied delays"
    
    def test_backoff_jitter_minimum(self):
        """Test that jitter doesn't go below minimum."""
        config = RetryConfig(
            max_retries=3,
            initial_delay=0.2,  # Very small initial delay
            max_delay=10.0,
            backoff_factor=1.0,
            jitter=True
        )
        
        # Even with negative jitter, should not go below 0.1s
        delay = calculate_backoff_delay(0, config)
        assert delay >= 0.1


class TestInvokeCopilotCli:
    """Tests for invoke_copilot_cli function."""
    
    def test_invoke_success(self, sample_work_item):
        """Test successful copilot invocation."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = iter(["Output line 1\n", "Output line 2\n"])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = None
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', mock_open()):
                with patch('os.unlink'):
                    with patch('builtins.open', mock_open(read_data="prompt")):
                        result = invoke_copilot_cli(sample_work_item)
                        
                        assert result.success
                        assert result.work_item_id == "test-123"
    
    def test_invoke_with_custom_prompt(self, sample_work_item):
        """Test invocation with custom prompt."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = iter(["Output\n"])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = None
        
        custom_prompt = "Custom prompt text"
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', mock_open()) as mock_file:
                with patch('os.unlink'):
                    result = invoke_copilot_cli(sample_work_item, prompt=custom_prompt)
                    
                    assert result.success
    
    def test_invoke_with_deny_write(self, sample_work_item):
        """Test invocation with deny_write flag (line 259)."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = iter(["Output\n"])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = None
        
        written_content = []
        
        def track_writes(content):
            written_content.append(content)
        
        mock_file_handle = MagicMock()
        mock_file_handle.write.side_effect = track_writes
        mock_file_handle.name = "temp_script.ps1"
        mock_file_handle.__enter__.return_value = mock_file_handle
        mock_file_handle.__exit__.return_value = False
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', return_value=mock_file_handle):
                with patch('os.unlink'):
                    result = invoke_copilot_cli(sample_work_item, deny_write=True)
                    
                    assert result.success
                    # Check that --deny-tool "write" and "edit" were written
                    script_content = ''.join(written_content)
                    assert '--deny-tool "write"' in script_content
                    assert '--deny-tool "edit"' in script_content
    
    def test_invoke_failure_non_zero_exit(self, sample_work_item):
        """Test handling of non-zero exit code (line 301)."""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = iter(["Error output\n"])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = "Error details"
        mock_process.wait.return_value = None
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', mock_open()):
                with patch('os.unlink'):
                    result = invoke_copilot_cli(sample_work_item)
                    
                    assert not result.success
                    assert "code 1" in result.error.lower()
    
    def test_invoke_tempfile_cleanup_exception(self, sample_work_item):
        """Test that tempfile cleanup exceptions are caught (line 321-322)."""
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.stdout = iter(["Output\n"])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = ""
        mock_process.wait.return_value = None
        
        # Make os.unlink raise an exception
        def unlink_side_effect(path):
            raise OSError("Permission denied")
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', mock_open()):
                with patch('os.unlink', side_effect=unlink_side_effect):
                    # Should not raise exception, cleanup errors are swallowed
                    result = invoke_copilot_cli(sample_work_item)
                    
                    assert result.success  # Main operation succeeded despite cleanup failure
    
    def test_invoke_generic_exception(self, sample_work_item):
        """Test handling of unexpected exceptions (line 367-377)."""
        # Simulate unexpected exception during Popen
        with patch('subprocess.Popen', side_effect=Exception("Unexpected error")):
            with patch('tempfile.NamedTemporaryFile', mock_open()):
                result = invoke_copilot_cli(sample_work_item)
                
                assert not result.success
                assert "Failed to invoke Copilot CLI" in result.error
                assert "Unexpected error" in result.error
    
    def test_invoke_retry_on_rate_limit(self, sample_work_item):
        """Test retry logic on rate limit error."""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = iter([])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = "Error 429: rate limit exceeded"
        mock_process.wait.return_value = None
        
        retry_config = RetryConfig(
            max_retries=2,
            initial_delay=0.1,
            max_delay=1.0,
            backoff_factor=2.0,
            jitter=False
        )
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', mock_open()):
                with patch('os.unlink'):
                    with patch('time.sleep'):  # Mock sleep to speed up test
                        result = invoke_copilot_cli(sample_work_item, retry_config=retry_config)
                        
                        assert not result.success
                        assert result.attempt_count == 3  # Initial + 2 retries
    
    def test_invoke_retry_on_transient_error(self, sample_work_item):
        """Test retry logic on transient error."""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = iter([])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = "Connection timeout"
        mock_process.wait.return_value = None
        
        retry_config = RetryConfig(
            max_retries=2,
            initial_delay=0.1,
            max_delay=1.0,
            backoff_factor=2.0,
            jitter=False
        )
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', mock_open()):
                with patch('os.unlink'):
                    with patch('time.sleep'):
                        result = invoke_copilot_cli(sample_work_item, retry_config=retry_config)
                        
                        assert not result.success
                        assert result.attempt_count == 3  # Initial + 2 retries
    
    def test_invoke_non_retryable_error(self, sample_work_item):
        """Test handling of non-retryable errors (line 301)."""
        mock_process = MagicMock()
        mock_process.returncode = 1
        mock_process.stdout = iter([])
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = "Syntax error: invalid command"
        mock_process.wait.return_value = None
        
        retry_config = RetryConfig(
            max_retries=2,
            initial_delay=0.1,
            max_delay=1.0,
            backoff_factor=2.0,
            jitter=False
        )
        
        with patch('subprocess.Popen', return_value=mock_process):
            with patch('tempfile.NamedTemporaryFile', mock_open()):
                with patch('os.unlink'):
                    # Non-retryable errors should fail on first attempt
                    result = invoke_copilot_cli(sample_work_item, retry_config=retry_config)
                    
                    assert not result.success
                    assert result.attempt_count == 1  # Should NOT retry
                    assert "code 1" in result.error.lower()
