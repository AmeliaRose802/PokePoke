"""Unit tests for agent_runner module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
import pytest

from pokepoke.agent_runner import (
    run_maintenance_agent,
    run_gate_agent,
    _run_beads_only_agent,
    _run_worktree_agent
)
from pokepoke.git_operations import has_uncommitted_changes, commit_all_changes
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult


class TestHasUncommittedChanges:
    """Test has_uncommitted_changes function."""
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_no_changes(self, mock_run: Mock) -> None:
        """Test repository with no uncommitted changes."""
        mock_run.return_value = Mock(
            stdout="",
            returncode=0
        )
        
        result = has_uncommitted_changes()
        
        assert result is False
        mock_run.assert_called_once_with(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=10,
            cwd=None
        )
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_has_changes(self, mock_run: Mock) -> None:
        """Test repository with uncommitted changes."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py",
            returncode=0
        )
        
        result = has_uncommitted_changes()
        
        assert result is True
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")
        
        result = has_uncommitted_changes()
        
        assert result is False


class TestCommitAllChanges:
    """Test commit_all_changes function."""
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_successful_commit(self, mock_run: Mock) -> None:
        """Test successful commit."""
        mock_run.return_value = Mock(returncode=0, stderr="")
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is True
        assert error_msg == ""
        assert mock_run.call_count == 2
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_commit_failure_with_errors(self, mock_run: Mock) -> None:
        """Test commit failure with error messages."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(
                returncode=1,
                stderr="error: pre-commit hook failed\nTests failed"
            )
        ]
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is False
        assert "pre-commit hook failed" in error_msg


class TestRunGateAgent:
    """Test run_gate_agent function."""
    
    @pytest.fixture
    def work_item(self) -> BeadsWorkItem:
        """Create a test work item."""
        return BeadsWorkItem(
            id="test-123",
            title="Test Fix",
            description="Fix the bug",
            status="in_progress",
            priority=1,
            issue_type="bug",
            labels=["test"]
        )
    
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.PromptService')
    def test_successful_verification_json(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test successful gate agent verification with JSON output."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "message": "All tests pass"}\n```',
            attempt_count=1
        )
        mock_parse.return_value = AgentStats(
            wall_duration=10.0, api_duration=5.0, input_tokens=100,
            output_tokens=50, lines_added=0, lines_removed=0, premium_requests=1
        )
        
        success, reason, stats = run_gate_agent(work_item)
        
        assert success is True
        assert "All tests pass" in reason
        assert stats is not None
        mock_invoke.assert_called_once_with(work_item, prompt="Gate prompt", deny_write=True, cwd=None)
    
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.PromptService')
    def test_failed_verification_json(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test failed gate agent verification with JSON output."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "failed", "reason": "Tests failed", "details": "3 tests failed"}\n```',
            attempt_count=1
        )
        mock_parse.return_value = None
        
        success, reason, stats = run_gate_agent(work_item)
        
        assert success is False
        assert "Tests failed" in reason
        assert "3 tests failed" in reason
    
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.PromptService')
    def test_successful_verification_text_fallback(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test successful verification using text fallback when JSON fails."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="VERIFICATION SUCCESSFUL - all checks pass",
            attempt_count=1
        )
        mock_parse.return_value = None
        
        success, reason, stats = run_gate_agent(work_item)
        
        assert success is True
        assert "text match" in reason
    
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.PromptService')
    def test_copilot_invocation_failure(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test gate agent when Copilot invocation fails."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=False,
            output="",
            error="Copilot CLI failed",
            attempt_count=1
        )
        
        success, reason, stats = run_gate_agent(work_item)
        
        assert success is False
        assert "execution failed" in reason
    
    @patch('pokepoke.agent_runner.PromptService')
    def test_prompt_render_failure(
        self,
        mock_service_cls: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test gate agent when prompt rendering fails."""
        mock_service = Mock()
        mock_service.load_and_render.side_effect = Exception("Template not found")
        mock_service_cls.return_value = mock_service
        
        success, reason, stats = run_gate_agent(work_item)
        
        assert success is False
        assert "Failed to render prompt" in reason
        assert stats is None
    
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.PromptService')
    def test_no_explicit_approval(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test when gate agent doesn't explicitly approve."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="I looked at the code but I'm not sure...",
            attempt_count=1
        )
        
        success, reason, stats = run_gate_agent(work_item)
        
        assert success is False
        assert "did not explicitly approve" in reason

    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.PromptService')
    def test_work_already_complete(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test gate agent recognizing work already complete on main branch."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "reason": "work_already_complete", '
                   '"message": "Fix already exists on main", '
                   '"recommendation": "Close as already-resolved"}\n```',
            attempt_count=1
        )
        mock_parse.return_value = None
        
        success, reason, stats = run_gate_agent(work_item)
        
        assert success is True
        assert "work_already_complete" in reason
        assert "Fix already exists on main" in reason
        assert "Close as already-resolved" in reason




class TestRunMaintenanceAgent:
    """Test run_maintenance_agent function."""
    
    @patch('pokepoke.agent_runner._run_beads_only_agent')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_beads_only_agent(
        self, 
        mock_cwd: Mock, 
        mock_exists: Mock, 
        mock_read: Mock, 
        mock_run_beads: Mock
    ) -> None:
        """Test running beads-only maintenance agent."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = True
        mock_read.return_value = "Agent instructions"
        mock_run_beads.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )
        
        stats = run_maintenance_agent(
            "TestAgent", 
            "test.md", 
            needs_worktree=False
        )
        
        assert stats is not None
        assert stats.wall_duration == 10.0
        mock_run_beads.assert_called_once()
    
    @patch('pokepoke.agent_runner._run_worktree_agent')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_worktree_agent(
        self, 
        mock_cwd: Mock, 
        mock_exists: Mock, 
        mock_read: Mock, 
        mock_run_wt: Mock
    ) -> None:
        """Test running worktree maintenance agent."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = True
        mock_read.return_value = "Agent instructions"
        mock_run_wt.return_value = AgentStats(
            wall_duration=20.0,
            api_duration=10.0,
            input_tokens=200,
            output_tokens=100,
            lines_added=10,
            lines_removed=5,
            premium_requests=2
        )
        
        stats = run_maintenance_agent(
            "TestAgent", 
            "test.md", 
            needs_worktree=True
        )
        
        assert stats is not None
        assert stats.wall_duration == 20.0
        mock_run_wt.assert_called_once()
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_missing_prompt_file(self, mock_cwd: Mock, mock_exists: Mock) -> None:
        """Test maintenance agent with missing prompt file."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = False
        
        stats = run_maintenance_agent("TestAgent", "missing.md")
        
        assert stats is None
    
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_prompts_dir_not_found(self, mock_get_dir: Mock) -> None:
        """Test maintenance agent when prompts directory not found."""
        mock_get_dir.side_effect = FileNotFoundError("Prompts directory not found")
        
        stats = run_maintenance_agent("TestAgent", "test.md")
        
        assert stats is None


class TestRunBeadsOnlyAgent:
    """Test _run_beads_only_agent function."""
    
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_successful_beads_agent(
        self, 
        mock_invoke: Mock, 
        mock_parse: Mock
    ) -> None:
        """Test successful beads-only agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )
        
        stats = _run_beads_only_agent("Test", agent_item, "Test prompt")
        
        assert stats is not None
        mock_invoke.assert_called_once_with(
            agent_item, 
            prompt="Test prompt", 
            deny_write=True,
            model=None,
            cwd=None
        )
    
    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_failed_beads_agent(self, mock_invoke: Mock) -> None:
        """Test failed beads-only agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=False,
            output="",
            error="Agent failed",
            attempt_count=1
        )
        
        stats = _run_beads_only_agent("Test", agent_item, "Test prompt")
        
        assert stats is None


class TestRunWorktreeAgent:
    """Test _run_worktree_agent function."""
    
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')  # Patch at module level
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_successful_worktree_agent(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup_loop: Mock,
        mock_parse: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_check_ready: Mock
    ) -> None:
        """Test successful worktree agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        mock_check_ready.return_value = (True, "")
        mock_merge.return_value = (True, [])  # Updated to return tuple
        
        stats = _run_worktree_agent(
            "Test", 
            "maintenance-test", 
            agent_item, 
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is not None
        mock_create.assert_called_once()
        mock_merge.assert_called_once_with("maintenance-test", cleanup=True)
        mock_cleanup.assert_not_called()
    
    @patch('pokepoke.agent_runner.create_worktree')
    def test_worktree_creation_failure(self, mock_create: Mock) -> None:
        """Test worktree agent when worktree creation fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.side_effect = Exception("Failed to create worktree")
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None
    
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_worktree_agent_failure(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test worktree agent when agent fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=False,
            output="",
            error="Agent failed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None

    @patch('pokepoke.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_worktree_merge_failure(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_check_ready: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_invoke_merge_cleanup: Mock
    ) -> None:
        """Test worktree agent when merge fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        # Mock successful agent run
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output='{"wall_duration": 10.0, "input_tokens": 100, "output_tokens": 50}',
            error="",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        
        # Repo ready, but merge fails
        mock_check_ready.return_value = (True, "")
        mock_merge.return_value = (False, ["conflicted_file.py"])  # Updated to return tuple
        
        # Cleanup fails too
        mock_invoke_merge_cleanup.return_value = (False, None)
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None
        # Verify cleanup invoked
        mock_invoke_merge_cleanup.assert_called_once()
        # With our new try-finally pattern, cleanup should be called in finally block
        mock_cleanup.assert_called_once_with("maintenance-test", force=True)
    
    @patch('pokepoke.git_operations.is_merge_in_progress')
    @patch('pokepoke.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_merge_cleanup_success_then_retry_succeeds(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_parse: Mock,
        mock_check_ready: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_invoke_merge_cleanup: Mock,
        mock_is_merge: Mock
    ) -> None:
        """Test merge conflict cleanup succeeds and retry works."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0, api_duration=5.0, input_tokens=100,
            output_tokens=50, lines_added=10, lines_removed=5, premium_requests=1
        )
        mock_check_ready.return_value = (True, "")
        
        # First merge fails, then succeeds
        mock_merge.side_effect = [(False, ["file.py"]), (True, [])]
        mock_invoke_merge_cleanup.return_value = (True, None)
        mock_is_merge.return_value = False  # No merge in progress after cleanup
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is not None
        mock_invoke_merge_cleanup.assert_called_once()
        assert mock_merge.call_count == 2
    
    @patch('pokepoke.git_operations.abort_merge')
    @patch('pokepoke.git_operations.is_merge_in_progress')
    @patch('pokepoke.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_merge_still_in_progress_after_cleanup_aborts(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_parse: Mock,
        mock_check_ready: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_invoke_merge_cleanup: Mock,
        mock_is_merge: Mock,
        mock_abort: Mock
    ) -> None:
        """Test merge is aborted when still in progress after cleanup."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0, api_duration=5.0, input_tokens=100,
            output_tokens=50, lines_added=10, lines_removed=5, premium_requests=1
        )
        mock_check_ready.return_value = (True, "")
        
        # Merge fails, cleanup succeeds, merge still in progress -> abort, retry works
        mock_merge.side_effect = [(False, ["file.py"]), (True, [])]
        mock_invoke_merge_cleanup.return_value = (True, None)
        mock_is_merge.return_value = True  # Merge still in progress after cleanup
        mock_abort.return_value = (True, None)
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is not None
        mock_abort.assert_called_once()  # Should abort merge
    
    @patch('pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_main_repo_not_ready_cleanup_fails(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_check_ready: Mock,
        mock_invoke_cleanup: Mock
    ) -> None:
        """Test when main repo not ready for merge and cleanup fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_check_ready.return_value = (False, "Uncommitted changes in main repo")
        mock_invoke_cleanup.return_value = (False, None)
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None
        mock_invoke_cleanup.assert_called_once()
    
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_main_repo_not_ready_cleanup_succeeds_but_still_fails(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_parse: Mock,
        mock_check_ready: Mock,
        mock_invoke_cleanup: Mock,
        mock_merge: Mock
    ) -> None:
        """Test when main repo not ready, cleanup succeeds, but still fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = None
        
        # First not ready, cleanup succeeds, still not ready
        mock_check_ready.side_effect = [
            (False, "Uncommitted changes"),
            (False, "Still uncommitted")
        ]
        mock_invoke_cleanup.return_value = (True, None)
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None


def _mcp_enabled_config() -> Mock:
    """Create a mock config with MCP server enabled."""
    cfg = Mock()
    cfg.mcp_server.enabled = True
    cfg.mcp_server.restart_script = "scripts/Restart-MCPServer.ps1"
    cfg.mcp_server.name = "Test MCP"
    return cfg


def _mcp_disabled_config() -> Mock:
    """Create a mock config with MCP server disabled."""
    cfg = Mock()
    cfg.mcp_server.enabled = False
    cfg.mcp_server.restart_script = None
    cfg.mcp_server.name = None
    return cfg


class TestRunBetaTester:
    """Test run_beta_tester function."""
    
    @patch('pokepoke.agent_runner.get_config')
    @patch('pokepoke.agent_runner._run_worktree_agent')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_success(
        self,
        mock_read: Mock,
        mock_exists: Mock,
        mock_run: Mock,
        mock_get_prompts: Mock,
        mock_parse: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock
    ) -> None:
        """Test successful beta tester run."""
        mock_get_config.return_value = _mcp_enabled_config()
        mock_exists.return_value = True
        mock_read.return_value = "Beta test prompt"
        mock_run.return_value = Mock(returncode=0)
        
        mock_worktree_agent.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        
        # Mock prompts dir
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Beta test prompt"
        mock_dir.__truediv__.return_value = mock_file
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        
        assert stats is not None
        assert stats.wall_duration == 10.0
        mock_worktree_agent.assert_called_once()
        # Verify call args have merge_changes=False
        args, kwargs = mock_worktree_agent.call_args
        assert kwargs.get('merge_changes') is False
        mock_run.assert_called()  # Restart script

    @patch('pokepoke.agent_runner.get_config')
    @patch('pokepoke.agent_runner._run_worktree_agent')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_restart_missing_keeps_going(
        self, 
        mock_read: Mock, 
        mock_exists: Mock, 
        mock_run: Mock, 
        mock_get_prompts: Mock,
        mock_parse: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock
    ) -> None:
        """Test restart script missing but proceeds."""
        mock_get_config.return_value = _mcp_enabled_config()
        # restart_script.exists() -> False
        # prompt_path.exists() -> True
        mock_exists.side_effect = [False, True]
        mock_read.return_value = "prompt"
        
        mock_worktree_agent.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        
        assert stats is not None # It proceeded!
        mock_run.assert_not_called() # Did not run restart

    @patch('pokepoke.agent_runner.get_config')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_beta_tester_prompt_missing(
        self, 
        mock_exists: Mock, 
        mock_run: Mock, 
        mock_get_prompts: Mock,
        mock_get_config: Mock
    ) -> None:
        """Test prompt file missing returns None."""
        mock_get_config.return_value = _mcp_enabled_config()
        # restart_script.exists() -> True
        # prompt_path.exists() -> False
        mock_exists.side_effect = [True, False]
        mock_run.return_value = Mock(returncode=0)
        
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = False # Explicitly false here too
        mock_dir.__truediv__.return_value = mock_file
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        assert stats is None

    @patch('pokepoke.agent_runner.get_config')
    @patch('pokepoke.agent_runner._run_worktree_agent')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_invoke_failure(
        self, 
        mock_read: Mock, 
        mock_exists: Mock, 
        mock_run: Mock, 
        mock_get_prompts: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock
    ) -> None:
        """Test beta tester returns None on invocation failure."""
        mock_get_config.return_value = _mcp_enabled_config()
        mock_exists.return_value = True
        mock_read.return_value = "prompt"
        mock_run.return_value = Mock(returncode=0)
        
        # Mock prompts dir
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file
        
        mock_worktree_agent.return_value = None
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        assert stats is None

    @patch('pokepoke.agent_runner.get_config')
    @patch('pokepoke.agent_runner._run_worktree_agent')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_restart_failure_keeps_going(
        self, 
        mock_read: Mock, 
        mock_exists: Mock, 
        mock_run: Mock, 
        mock_get_prompts: Mock,
        mock_parse: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock
    ) -> None:
        """Test restart script execution failure but proceeds."""
        mock_get_config.return_value = _mcp_enabled_config()
        mock_exists.return_value = True
        mock_read.return_value = "prompt"
        
        # Restart fails
        mock_run.return_value = Mock(returncode=1, stdout="Error")
        
        mock_worktree_agent.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        
        assert stats is not None
        mock_run.assert_called_once()


class TestRunMainRepoAgent:
    """Test _run_main_repo_agent function."""

    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_successful_main_repo_agent(
        self,
        mock_invoke: Mock,
        mock_parse: Mock
    ) -> None:
        """Test successful main repo agent with write access."""
        from pokepoke.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="worktree-cleanup",
            title="Worktree Cleanup",
            description="Clean up worktrees",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="worktree-cleanup",
            success=True,
            output="Completed cleanup",
            attempt_count=1
        )
        mock_parse.return_value = AgentStats(
            wall_duration=15.0,
            api_duration=8.0,
            input_tokens=200,
            output_tokens=100,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )

        stats = _run_main_repo_agent("Worktree Cleanup", agent_item, "cleanup prompt")

        assert stats is not None
        assert stats.wall_duration == 15.0
        # Verify deny_write=False (write access enabled)
        mock_invoke.assert_called_once_with(
            agent_item, prompt="cleanup prompt", deny_write=False, model=None, cwd=None
        )

    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_failed_main_repo_agent(self, mock_invoke: Mock) -> None:
        """Test failed main repo agent returns None."""
        from pokepoke.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="worktree-cleanup",
            title="Worktree Cleanup",
            description="Clean up worktrees",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="worktree-cleanup",
            success=False,
            output="",
            error="Agent crashed",
            attempt_count=1
        )

        stats = _run_main_repo_agent("Worktree Cleanup", agent_item, "cleanup prompt")
        assert stats is None

    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_main_repo_agent_write_access_not_denied(
        self,
        mock_invoke: Mock,
        mock_parse: Mock
    ) -> None:
        """Verify main repo agent does NOT use deny_write=True."""
        from pokepoke.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="test-agent",
            title="Test",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=[]
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-agent",
            success=True,
            output="Done",
            attempt_count=1
        )
        mock_parse.return_value = None

        _run_main_repo_agent("Test", agent_item, "prompt")

        _, kwargs = mock_invoke.call_args
        assert kwargs['deny_write'] is False

    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_main_repo_agent_with_model(
        self,
        mock_invoke: Mock,
        mock_parse: Mock
    ) -> None:
        """Test main repo agent passes model parameter."""
        from pokepoke.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="test",
            title="Test",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=[]
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="test",
            success=True,
            output="Done",
            attempt_count=1
        )
        mock_parse.return_value = None

        _run_main_repo_agent("Test", agent_item, "prompt", model="gpt-5.1-codex")

        _, kwargs = mock_invoke.call_args
        assert kwargs['model'] == "gpt-5.1-codex"


class TestRunWorktreeCleanup:
    """Test run_worktree_cleanup function."""

    @patch('pokepoke.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_success(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock
    ) -> None:
        """Test successful worktree cleanup run."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Worktree cleanup prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = AgentStats(
            wall_duration=30.0,
            api_duration=15.0,
            input_tokens=500,
            output_tokens=200,
            lines_added=0,
            lines_removed=0,
            premium_requests=2
        )

        from pokepoke.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()

        assert stats is not None
        assert stats.wall_duration == 30.0
        mock_main_repo_agent.assert_called_once()
        # Verify it uses _run_main_repo_agent (not worktree or beads-only)
        args, _ = mock_main_repo_agent.call_args
        assert args[0] == "Worktree Cleanup"

    @patch('pokepoke.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_failure(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock
    ) -> None:
        """Test worktree cleanup returns None on failure."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        from pokepoke.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()
        assert stats is None

    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_prompt_missing(
        self,
        mock_get_prompts: Mock
    ) -> None:
        """Test worktree cleanup when prompt file is missing."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_file

        from pokepoke.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()
        assert stats is None

    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_prompts_dir_not_found(
        self,
        mock_get_prompts: Mock
    ) -> None:
        """Test worktree cleanup when prompts directory not found."""
        mock_get_prompts.side_effect = FileNotFoundError("Prompts not found")

        from pokepoke.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()
        assert stats is None

    @patch('pokepoke.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_with_repo_root_passes_cwd(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock
    ) -> None:
        """Test worktree cleanup passes repo_root as cwd instead of chdir."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        from pokepoke.agent_runner import run_worktree_cleanup
        run_worktree_cleanup(repo_root=Path("/main/repo"))

        # Should pass cwd to _run_main_repo_agent instead of using os.chdir
        mock_main_repo_agent.assert_called_once()
        _, kwargs = mock_main_repo_agent.call_args
        assert kwargs.get("cwd") == str(Path("/main/repo"))

    @patch('pokepoke.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_error_propagates(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock
    ) -> None:
        """Test worktree cleanup propagates agent errors without chdir."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.side_effect = RuntimeError("Agent exploded")

        from pokepoke.agent_runner import run_worktree_cleanup
        with pytest.raises(RuntimeError, match="Agent exploded"):
            run_worktree_cleanup(repo_root=Path("/main/repo"))

    @patch('pokepoke.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_no_repo_root_no_chdir(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock
    ) -> None:
        """Test worktree cleanup without repo_root doesn't change directory."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        with patch('os.chdir') as mock_chdir:
            from pokepoke.agent_runner import run_worktree_cleanup
            run_worktree_cleanup()  # No repo_root
            mock_chdir.assert_not_called()

    @patch('pokepoke.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_loads_correct_prompt_file(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock
    ) -> None:
        """Test worktree cleanup loads worktree-cleanup.md prompt."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Worktree cleanup instructions"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        from pokepoke.agent_runner import run_worktree_cleanup
        run_worktree_cleanup()

        # Verify it loads worktree-cleanup.md
        mock_dir.__truediv__.assert_called_with("worktree-cleanup.md")
