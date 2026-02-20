"""Tests for repository check utilities."""

from contextlib import nullcontext
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.repo_check import check_and_commit_main_repo, _try_auto_commit


@pytest.fixture(autouse=True)
def _mock_cleanup_lock(monkeypatch):
    """Replace cleanup_lock with a noop context manager."""
    monkeypatch.setattr("pokepoke.repo_check.cleanup_lock", lambda: nullcontext())


class TestCheckAndCommitMainRepo:
    """Test check_and_commit_main_repo function."""

    def test_clean_repository_returns_true(self):
        """Test that a clean repository returns True."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            # Mock git status showing no changes
            mock_run.return_value = Mock(
                returncode=0,
                stdout="",
                stderr=""
            )

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == ["git", "status", "--porcelain"]

    def test_beads_changes_only_continues(self):
        """Test that only beads changes allows continuation."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('builtins.print') as mock_print:
            # Mock git status showing only beads changes
            mock_run.return_value = Mock(
                returncode=0,
                stdout=" M .beads/database.json\n M .beads/cache/item1.json",
                stderr=""
            )

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            # Should print info about beads sync
            assert any("Beads database changes" in str(call) for call in mock_print.call_args_list)

    def test_worktree_changes_auto_commit(self):
        """Test that worktree changes are automatically committed."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            # First call: git status showing worktree changes
            # Subsequent calls: git add and git commit
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" D worktrees/task-1/file.py", stderr=""),
                Mock(returncode=0),  # git add
                Mock(returncode=0)   # git commit
            ]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            assert mock_run.call_count == 3
            # Check git add was called
            assert mock_run.call_args_list[1][0][0] == ["git", "add", "worktrees/"]
            # Check git commit was called
            assert "git" in mock_run.call_args_list[2][0][0]
            assert "commit" in mock_run.call_args_list[2][0][0]

    def test_git_status_failure_not_a_repo(self):
        """Test handling git status failure when not a git repo."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists') as mock_exists:
            # Mock git status failing
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=128,
                cmd=["git", "status"],
                stderr="fatal: not a git repository"
            )
            # Mock .git directory not existing
            mock_exists.return_value = False

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is False
            mock_logger.log_orchestrator.assert_any_call(
                f"{repo_path} is not a git repository",
                level="ERROR"
            )

    def test_git_status_failure_other_error_continues(self):
        """Test that other git errors allow continuation."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists') as mock_exists:
            # Mock git status failing
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["git", "status"],
                stderr="some other error"
            )
            # Mock .git directory existing
            mock_exists.return_value = True

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_logger.log_orchestrator.assert_any_call(
                "git status failed: some other error",
                level="WARNING"
            )

    def test_other_changes_auto_commit_success_skips_cleanup(self):
        """Test that successful auto-commit skips cleanup agent."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            # git status, git add, git commit
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/module.py\n M README.md", stderr=""),
                Mock(returncode=0),  # git add --all
                Mock(returncode=0, stdout="", stderr=""),  # git commit
            ]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            # Should NOT have invoked cleanup agent
            assert mock_run.call_count == 3
            mock_logger.log_orchestrator.assert_any_call("Auto-committed uncommitted changes")

    def test_other_changes_auto_commit_fails_invokes_cleanup(self):
        """Test that failed auto-commit falls back to cleanup agent."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup:
            # git status, git add (auto-commit), git commit fails, then cleanup agent
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/module.py\n M README.md", stderr=""),
                Mock(returncode=0),  # git add --all (auto-commit)
                Mock(returncode=1, stdout="", stderr="pre-commit hook failed"),  # git commit fails
            ]
            # Mock cleanup agent succeeding
            mock_cleanup.return_value = (True, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_cleanup.assert_called_once()
            cleanup_item = mock_cleanup.call_args[0][0]
            assert cleanup_item.id == "cleanup-main-repo-1"
            assert "uncommitted changes" in cleanup_item.title.lower()

    def test_auto_commit_and_cleanup_failure_retries_and_stashes(self):
        """Test that auto-commit + cleanup agent failure triggers retries then stash."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.repo_check.time.sleep'):  # Speed up test
            # git status, auto-commit (add + commit fail), then stash commands
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/module.py", stderr=""),  # git status
                Mock(returncode=0),  # git add --all (auto-commit)
                Mock(returncode=1, stdout="", stderr="hook failed"),  # git commit fails
                Mock(returncode=0),  # git add --all for stash
                Mock(returncode=0, stdout="", stderr="")  # git stash push
            ]
            # Mock cleanup agent failing all 3 times
            mock_cleanup.return_value = (False, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            # Should return True because stash succeeded
            assert result is True
            # Should have tried cleanup 3 times (MAX_CLEANUP_RETRIES)
            assert mock_cleanup.call_count == 3
            # Should log that stash was successful
            mock_logger.log_orchestrator.assert_any_call("Uncommitted changes stashed successfully")

    def test_all_fallbacks_fail_continues_anyway(self):
        """Test that auto-commit + cleanup + stash failure still continues."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.repo_check.time.sleep'):  # Speed up test
            # git status, auto-commit fails, then stash also fails
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/module.py", stderr=""),  # git status
                Mock(returncode=0),  # git add --all (auto-commit)
                Mock(returncode=1, stdout="", stderr="hook failed"),  # git commit fails
                Mock(returncode=0),  # git add --all (stash)
                Mock(returncode=1, stdout="", stderr="cannot stash")  # git stash fails
            ]
            # Mock cleanup agent failing all 3 times
            mock_cleanup.return_value = (False, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            # Should STILL return True - workers use isolated worktrees
            assert result is True
            mock_logger.log_orchestrator.assert_any_call(
                "Cleanup and stash both failed, but continuing (workers use worktrees)",
                level="WARNING"
            )

    def test_cleanup_succeeds_on_second_retry(self):
        """Test that cleanup succeeding on retry returns True without stash."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.repo_check.time.sleep'):  # Speed up test
            # git status, auto-commit fails
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/module.py", stderr=""),
                Mock(returncode=0),  # git add --all (auto-commit)
                Mock(returncode=1, stdout="", stderr="hook failed"),  # git commit fails
            ]
            # Mock cleanup agent failing first, succeeding second
            mock_cleanup.side_effect = [(False, Mock()), (True, Mock())]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            # Should have tried cleanup twice
            assert mock_cleanup.call_count == 2
            # Should log success
            mock_logger.log_orchestrator.assert_any_call(
                "Cleanup agent successfully resolved uncommitted changes"
            )

    def test_untracked_files_ignored(self):
        """Test that untracked files don't trigger cleanup agent."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            # Mock git status showing only untracked files
            mock_run.return_value = Mock(
                returncode=0,
                stdout="?? new_file.py\n?? temp/",
                stderr=""
            )

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True

    def test_mixed_changes_tries_auto_commit_first(self):
        """Test that mixed changes (beads + other) try auto-commit before cleanup."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            # git status, auto-commit succeeds
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M .beads/database.json\n M src/main.py", stderr=""),
                Mock(returncode=0),  # git add --all
                Mock(returncode=0, stdout="", stderr=""),  # git commit
            ]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_logger.log_orchestrator.assert_any_call("Auto-committed uncommitted changes")

    def test_many_other_changes_truncated_output(self):
        """Test that many changes are truncated in output."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('builtins.print') as mock_print:
            # Mock git status with 15 changes, auto-commit succeeds
            changes = [f" M file{i}.py" for i in range(15)]
            mock_run.side_effect = [
                Mock(returncode=0, stdout="\n".join(changes), stderr=""),
                Mock(returncode=0),  # git add --all
                Mock(returncode=0, stdout="", stderr=""),  # git commit
            ]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            # Should print "and X more" message
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any("and 5 more" in call for call in print_calls)

    def test_git_error_no_stderr(self):
        """Test git error handling when stderr is empty."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists') as mock_exists:
            # Mock git status failing with no stderr
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["git", "status"],
                stderr=""
            )
            mock_exists.return_value = True

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            # Should use "exit code X" format
            log_calls = [str(call) for call in mock_logger.log_orchestrator.call_args_list]
            assert any("exit code 1" in call for call in log_calls)


class TestTryAutoCommit:
    """Test _try_auto_commit function."""

    def test_auto_commit_success(self):
        """Test successful auto-commit."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0),  # git add --all
                Mock(returncode=0, stdout="", stderr=""),  # git commit
            ]

            result = _try_auto_commit(repo_path, mock_logger)

            assert result is True
            mock_logger.log_orchestrator.assert_any_call("Auto-committed uncommitted changes")

    def test_auto_commit_hook_failure(self):
        """Test auto-commit fails when pre-commit hooks reject."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0),  # git add --all
                Mock(returncode=1, stdout="", stderr="pre-commit hook failed"),  # git commit fails
            ]

            result = _try_auto_commit(repo_path, mock_logger)

            assert result is False

    def test_auto_commit_git_add_fails(self):
        """Test auto-commit fails when git add fails."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=128, cmd=["git", "add"], stderr="error"
            )

            result = _try_auto_commit(repo_path, mock_logger)

            assert result is False

    def test_auto_commit_timeout(self):
        """Test auto-commit handles timeout."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=120)

            result = _try_auto_commit(repo_path, mock_logger)

            assert result is False
            mock_logger.log_orchestrator.assert_any_call("Auto-commit timed out", level="WARNING")
