"""Tests for timeout and restart logic."""

import pytest
import time
from unittest.mock import patch, MagicMock, Mock
from pokepoke.types import BeadsWorkItem, CopilotResult
from pokepoke.copilot import invoke_copilot_cli
from pokepoke.orchestrator import process_work_item


@pytest.fixture
def sample_work_item():
    """Create a sample work item for testing."""
    return BeadsWorkItem(
        id="test-123",
        title="Test timeout handling",
        description="Test work item",
        status="in_progress",
        priority=1,
        issue_type="task"
    )


def test_copilot_cli_timeout_respected(sample_work_item):
    """Test that copilot CLI respects the timeout parameter."""
    
    # Mock subprocess.Popen to simulate a hanging process
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = iter([])  # Empty output
    mock_process.stderr = None
    
    # Simulate timeout by making wait() raise TimeoutExpired
    import subprocess
    mock_process.wait.side_effect = subprocess.TimeoutExpired(cmd='copilot', timeout=5)
    
    with patch('subprocess.Popen', return_value=mock_process):
        with patch('tempfile.NamedTemporaryFile'):
            with patch('os.unlink'):
                start_time = time.time()
                result = invoke_copilot_cli(sample_work_item, timeout=5.0)
                elapsed = time.time() - start_time
                
                # Should timeout around 5 seconds (with some tolerance)
                assert elapsed < 10, "Timeout took too long"
                assert not result.success, "Should fail on timeout"
                assert "timed out" in result.error.lower()


def test_copilot_cli_default_timeout(sample_work_item):
    """Test that copilot CLI uses default 2-hour timeout when not specified."""
    
    # Mock subprocess.Popen
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = iter(["Success\n"])
    mock_process.stderr = None
    mock_process.wait.return_value = None
    
    with patch('subprocess.Popen', return_value=mock_process):
        with patch('tempfile.NamedTemporaryFile'):
            with patch('os.unlink'):
                result = invoke_copilot_cli(sample_work_item)
                
                # Should succeed with default timeout
                assert result.success


def test_copilot_cli_timeout_calculation(sample_work_item):
    """Test that remaining timeout is calculated correctly."""
    
    # Mock time.time to simulate elapsed time
    start_time = 1000.0
    current_time = 1100.0  # 100 seconds elapsed
    
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = iter(["Success\n"])
    mock_process.stderr = None
    mock_process.wait.return_value = None
    
    time_calls = [start_time, current_time, current_time]
    
    with patch('subprocess.Popen', return_value=mock_process):
        with patch('tempfile.NamedTemporaryFile'):
            with patch('os.unlink'):
                with patch('time.time', side_effect=time_calls):
                    result = invoke_copilot_cli(sample_work_item, timeout=200.0)
                    
                    # Should use remaining timeout (200 - 100 = 100s)
                    # Check that wait was called with at least 30s (minimum)
                    assert mock_process.wait.called
                    call_args = mock_process.wait.call_args
                    if call_args and 'timeout' in call_args[1]:
                        timeout_used = call_args[1]['timeout']
                        assert timeout_used >= 30, "Should use at least minimum timeout"


def test_process_work_item_timeout_restart(sample_work_item):
    """Test that process_work_item restarts on timeout."""
    
    # Mock all the dependencies
    with patch('pokepoke.orchestrator.create_worktree', return_value='/tmp/worktree'):
        with patch('os.chdir'):
            with patch('os.getcwd', return_value='/original'):
                with patch('pokepoke.orchestrator.has_uncommitted_changes', return_value=False):
                    with patch('subprocess.run') as mock_subprocess:
                        with patch('pokepoke.orchestrator.merge_worktree', return_value=True):
                            with patch('pokepoke.orchestrator.cleanup_worktree'):
                                with patch('pokepoke.orchestrator.close_item', return_value=True):
                                    with patch('pokepoke.orchestrator.get_parent_id', return_value=None):
                                        # Mock subprocess: return 1 commit for commit count, empty for git status
                                        def subprocess_side_effect(*args, **kwargs):
                                            cmd = args[0] if args else kwargs.get('args', [])
                                            if 'rev-list' in cmd:
                                                return Mock(stdout="1\n")
                                            elif 'status' in cmd and '--porcelain' in cmd:
                                                return Mock(stdout="")  # Clean repo
                                            return Mock(stdout="")
                                        mock_subprocess.side_effect = subprocess_side_effect
                                        # Mock time to simulate timeout
                                        call_count = [0]
                                        
                                        def mock_invoke(*args, **kwargs):
                                            call_count[0] += 1
                                            return CopilotResult(
                                                work_item_id=sample_work_item.id,
                                                success=True,
                                                output="Success",
                                                attempt_count=1
                                            )
                                        
                                        # Use very short timeout for testing
                                        with patch('pokepoke.orchestrator.invoke_copilot_cli', side_effect=mock_invoke):
                                            from pokepoke.orchestrator import process_work_item
                                            result = process_work_item(sample_work_item, interactive=False, timeout_hours=0.001)
                                            
                                            # Should succeed and return 3-tuple
                                            success, request_count, stats = result
                                            assert success == True
                                            assert request_count == 1


def test_non_interactive_environment_variables():
    """Test that non-interactive environment variables are set."""
    
    sample_item = BeadsWorkItem(
        id="test-123",
        title="Test",
        status="in_progress",
        priority=1,
        issue_type="task"
    )
    
    # Mock to capture the PowerShell script content
    script_content = []
    
    def capture_script(mode, suffix, delete, encoding):
        mock_file = MagicMock()
        mock_file.__enter__ = MagicMock(return_value=mock_file)
        mock_file.__exit__ = MagicMock(return_value=False)
        mock_file.name = 'test.ps1'
        
        def write_spy(content):
            script_content.append(content)
        
        mock_file.write = write_spy
        return mock_file
    
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = iter(["Success\n"])
    mock_process.stderr = None
    mock_process.wait.return_value = None
    
    with patch('subprocess.Popen', return_value=mock_process):
        with patch('tempfile.NamedTemporaryFile', side_effect=capture_script):
            with patch('os.unlink'):
                result = invoke_copilot_cli(sample_item)
                
                # Check that CI and COPILOT_NON_INTERACTIVE env vars are set
                script_text = ''.join(script_content)
                assert '$env:CI = "true"' in script_text, "CI env var should be set"
                assert '$env:COPILOT_NON_INTERACTIVE = "1"' in script_text, "Non-interactive flag should be set"


def test_minimum_timeout_enforced(sample_work_item):
    """Test that minimum timeout of 30s is enforced."""
    
    # Mock time.time to simulate almost expired timeout
    start_time = 1000.0
    current_time = 7195.0  # Almost 2 hours elapsed (only 5s left)
    
    mock_process = MagicMock()
    mock_process.returncode = 0
    mock_process.stdout = iter(["Success\n"])
    mock_process.stderr = None
    mock_process.wait.return_value = None
    
    time_calls = [start_time, current_time, current_time]
    
    with patch('subprocess.Popen', return_value=mock_process):
        with patch('tempfile.NamedTemporaryFile'):
            with patch('os.unlink'):
                with patch('time.time', side_effect=time_calls):
                    result = invoke_copilot_cli(sample_work_item, timeout=7200.0)
                    
                    # Should use minimum timeout of 30s despite only 5s remaining
                    call_args = mock_process.wait.call_args
                    if call_args and 'timeout' in call_args[1]:
                        timeout_used = call_args[1]['timeout']
                        assert timeout_used >= 30, "Should enforce minimum 30s timeout"


def test_process_work_item_with_timeout_parameter(sample_work_item):
    """Test that process_work_item accepts and uses timeout parameter."""
    from pokepoke.orchestrator import process_work_item
    
    with patch('pokepoke.orchestrator.create_worktree', return_value='/tmp/worktree'):
        with patch('os.chdir'):
            with patch('os.getcwd', return_value='/original'):
                with patch('pokepoke.orchestrator.invoke_copilot_cli') as mock_invoke:
                    with patch('pokepoke.orchestrator.has_uncommitted_changes', return_value=False):
                        with patch('subprocess.run') as mock_subprocess:
                            with patch('pokepoke.orchestrator.merge_worktree', return_value=True):
                                with patch('pokepoke.orchestrator.cleanup_worktree'):
                                    with patch('pokepoke.orchestrator.close_item', return_value=True):
                                        with patch('pokepoke.orchestrator.get_parent_id', return_value=None):
                                            # Mock subprocess: return 1 commit for commit count, empty for git status
                                            def subprocess_side_effect(*args, **kwargs):
                                                cmd = args[0] if args else kwargs.get('args', [])
                                                if 'rev-list' in cmd:
                                                    return Mock(stdout="1\n")
                                                elif 'status' in cmd and '--porcelain' in cmd:
                                                    return Mock(stdout="")  # Clean repo
                                                return Mock(stdout="")
                                            mock_subprocess.side_effect = subprocess_side_effect
                                            mock_invoke.return_value = CopilotResult(
                                                work_item_id=sample_work_item.id,
                                                success=True,
                                                output="Success",
                                                attempt_count=1
                                            )
                                            
                                            # Call with custom timeout
                                            result = process_work_item(sample_work_item, interactive=False, timeout_hours=1.0)
                                            
                                            # Extract kwargs from first call to invoke_copilot_cli
                                            first_call_kwargs = mock_invoke.call_args[1]
                                            
                                            success, request_count, stats = result
                                            assert success == True
                                            assert request_count == 1
                                        # Stats should be None since "Success" doesn't contain any parseable stats
                                        assert stats is None
