"""Tests for repository check utilities."""

import subprocess
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.git.repo_check import (
    _detect_conflict_marker_files,
    _restore_conflicted_files,
    _stash_uncommitted_changes,
    _try_auto_commit,
    check_and_commit_main_repo,
    check_beads_available,
    initialize_beads_repo,
)


@pytest.fixture(autouse=True)
def _mock_cleanup_lock(monkeypatch):
    """Replace cleanup_lock with a noop context manager."""
    monkeypatch.setattr("pokepoke.git.repo_check.cleanup_lock", lambda: nullcontext())


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

    def test_worktree_changes_treated_as_other(self):
        """Test that worktree changes (if any) are treated as 'other' changes.

        worktrees/ is gitignored so changes should never appear in git status.
        If they do (e.g. force-added), they fall into the 'other' bucket and
        get handled by the general auto-commit path.
        """
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            # git status showing worktree file (force-added edge case)
            # then git add -u + git commit via _try_auto_commit
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" D worktrees/task-1/file.py", stderr=""),
                Mock(returncode=0),  # git add -u
                Mock(returncode=0),  # git commit
            ]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            # Should go through _handle_other_changes → _try_auto_commit
            assert mock_run.call_count == 3
            # git add -u (not git add worktrees/)
            assert mock_run.call_args_list[1][0][0] == ["git", "add", "-u"]

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
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]):
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
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]), \
             patch('pokepoke.git.repo_check._restore_conflicted_files', return_value=False), \
             patch('pokepoke.git.repo_check._try_reset_working_tree', return_value=False), \
             patch('pokepoke.git.repo_check.time.sleep'):  # Speed up test
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
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]), \
             patch('pokepoke.git.repo_check._restore_conflicted_files', return_value=False), \
             patch('pokepoke.git.repo_check._try_reset_working_tree', return_value=False), \
             patch('pokepoke.git.repo_check.time.sleep'):  # Speed up test
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
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]), \
             patch('pokepoke.git.repo_check.time.sleep'):  # Speed up test
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
        """Test that many changes are handled and only first 10 logged."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            # Mock git status with 15 changes, auto-commit succeeds
            changes = [f" M file{i}.py" for i in range(15)]
            mock_run.side_effect = [
                Mock(returncode=0, stdout="\n".join(changes), stderr=""),
                Mock(returncode=0),  # git add --all
                Mock(returncode=0, stdout="", stderr=""),  # git commit
            ]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True

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


    def test_cleanup_aggregate_timeout_triggers_stash(self):
        """Test that aggregate timeout causes cleanup loop to break and attempt stash."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]), \
             patch('pokepoke.git.repo_check._restore_conflicted_files', return_value=False), \
             patch('pokepoke.git.repo_check._try_reset_working_tree', return_value=False), \
             patch('pokepoke.git.repo_check.time.sleep'), \
             patch('pokepoke.git.repo_check.time.monotonic') as mock_mono:
            # monotonic: start=0, first check exceeds threshold
            from pokepoke.utils.constants import CLEANUP_AGGREGATE_TIMEOUT
            mock_mono.side_effect = [0.0, CLEANUP_AGGREGATE_TIMEOUT + 1.0]

            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/module.py", stderr=""),  # git status
                Mock(returncode=0),  # git add --all (auto-commit)
                Mock(returncode=1, stdout="", stderr="hook failed"),  # git commit fails
                Mock(returncode=0),  # git add --all (stash)
                Mock(returncode=0, stdout="", stderr=""),  # git stash push
            ]
            # Cleanup should never be called because timeout triggers first
            mock_cleanup.return_value = (False, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            # Should still return True (stash succeeds, workers use worktrees)
            assert result is True
            # Cleanup was never called because aggregate timeout broke the loop
            mock_cleanup.assert_not_called()
            mock_logger.log_orchestrator.assert_any_call(
                f"Cleanup aggregate timeout ({CLEANUP_AGGREGATE_TIMEOUT:.0f}s) exceeded",
                level="WARNING",
            )


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

    def test_auto_commit_unexpected_exception(self):
        """Test auto-commit handles unexpected exceptions."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = OSError("Unexpected error")

            result = _try_auto_commit(repo_path, mock_logger)

            assert result is False

    def test_auto_commit_uses_tracked_only(self):
        """Auto-commit uses git add -u to avoid staging untracked .pokepoke/ files."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0),  # git add -u
                Mock(returncode=0, stdout="", stderr=""),  # git commit
            ]

            _try_auto_commit(repo_path, mock_logger)

            # First call should be git add -u (not --all)
            add_call = mock_run.call_args_list[0]
            add_cmd = add_call[0][0]
            assert add_cmd == ["git", "add", "-u"], f"Expected git add -u, got {add_cmd}"


class TestStashUncommittedChanges:
    """Test _stash_uncommitted_changes function."""

    def test_stash_success(self):
        """Test successful stash."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0),  # git add --all
                Mock(returncode=0, stdout="", stderr=""),  # git stash push
            ]

            result = _stash_uncommitted_changes(repo_path, mock_logger)

            assert result is True

    def test_stash_failure(self):
        """Test stash when git stash fails."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0),  # git add --all
                Mock(returncode=1, stdout="", stderr="cannot stash"),  # git stash fails
            ]

            result = _stash_uncommitted_changes(repo_path, mock_logger)

            assert result is False

    def test_stash_timeout(self):
        """Test stash when git stash times out."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0),  # git add --all
                subprocess.TimeoutExpired(cmd="git", timeout=60),
            ]

            result = _stash_uncommitted_changes(repo_path, mock_logger)

            assert result is False

    def test_stash_git_add_fails(self):
        """Test stash when git add fails."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=128, cmd=["git", "add"], stderr="error"
            )

            result = _stash_uncommitted_changes(repo_path, mock_logger)

            assert result is False

    def test_stash_unexpected_exception(self):
        """Test stash when unexpected exception occurs."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = OSError("Unexpected")

            result = _stash_uncommitted_changes(repo_path, mock_logger)

            assert result is False

    def test_stash_uses_tracked_only(self):
        """Stash uses git add -u to avoid staging untracked .pokepoke/ files."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                Mock(returncode=0),  # git add -u
                Mock(returncode=0, stdout="", stderr=""),  # git stash push
            ]

            _stash_uncommitted_changes(repo_path, mock_logger)

            # First call should be git add -u (not --all)
            add_call = mock_run.call_args_list[0]
            add_cmd = add_call[0][0]
            assert add_cmd == ["git", "add", "-u"], f"Expected git add -u, got {add_cmd}"


class TestCheckBeadsAvailable:
    """Test check_beads_available function."""

    @patch('shutil.which')
    def test_bd_not_installed(self, mock_which):
        """Test when bd command is not installed."""
        mock_which.return_value = None

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_available_and_initialized(self, mock_which, tmp_path, monkeypatch):
        """Test when bd is available and .beads directory is initialized."""
        monkeypatch.chdir(tmp_path)
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "config.yaml").write_text("test: true")

        result = check_beads_available()

        assert result is True

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_not_initialized(self, mock_which, tmp_path, monkeypatch):
        """Test when bd is installed but .beads directory doesn't exist."""
        monkeypatch.chdir(tmp_path)

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_timeout(self, mock_which, tmp_path, monkeypatch):
        """Test returns False when .beads directory has no marker files."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".beads").mkdir()

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_exception(self, mock_which, tmp_path, monkeypatch):
        """Test returns False when .beads directory is incomplete."""
        monkeypatch.chdir(tmp_path)
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "random.txt").write_text("not a marker")

        result = check_beads_available()

        assert result is False


class TestInitializeBeadsRepo:
    """Test initialize_beads_repo function."""

    @patch('shutil.which')
    def test_bd_not_installed(self, mock_which):
        """Test when bd command is not installed."""
        mock_which.return_value = None

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_already_initialized(self, mock_run, mock_which):
        """Test when beads is already initialized."""
        mock_run.return_value = Mock(returncode=0, stdout='{}', stderr='')

        result = initialize_beads_repo(Path("/repo"))

        assert result is True

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_init_success(self, mock_run, mock_which):
        """Test successful beads initialization."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='not init'),  # bd info (not initialized)
            Mock(returncode=0, stdout='', stderr=''),  # bd init
            Mock(returncode=0, stdout='{}', stderr=''),  # bd info (verify)
        ]

        result = initialize_beads_repo(Path("/repo"))

        assert result is True

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_init_fails(self, mock_run, mock_which):
        """Test when bd init fails."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='not init'),  # bd info
            Mock(returncode=1, stdout='', stderr='init failed'),  # bd init fails
        ]

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_info_timeout_before_init(self, mock_run, mock_which):
        """Test when bd info times out before init."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bd", timeout=30)

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_info_exception_before_init(self, mock_run, mock_which):
        """Test when bd info raises exception before init."""
        mock_run.side_effect = OSError("Permission denied")

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_init_timeout(self, mock_run, mock_which):
        """Test when bd init times out."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='not init'),
            subprocess.TimeoutExpired(cmd="bd", timeout=120),
        ]

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_init_exception(self, mock_run, mock_which):
        """Test when bd init raises exception."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='not init'),
            OSError("Cannot run bd init"),
        ]

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_verify_fails_after_init(self, mock_run, mock_which):
        """Test when verification after init fails."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='not init'),  # bd info
            Mock(returncode=0, stdout='', stderr=''),  # bd init succeeds
            Mock(returncode=1, stdout='', stderr='still not init'),  # bd info verify fails
        ]

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_verify_timeout_after_init(self, mock_run, mock_which):
        """Test when verification after init times out."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='not init'),
            Mock(returncode=0, stdout='', stderr=''),  # bd init succeeds
            subprocess.TimeoutExpired(cmd="bd", timeout=30),  # verify times out
        ]

        result = initialize_beads_repo(Path("/repo"))

        assert result is False

    @patch('shutil.which', return_value='/usr/bin/bd')
    @patch('subprocess.run')
    def test_verify_exception_after_init(self, mock_run, mock_which):
        """Test when verification after init raises exception."""
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='not init'),
            Mock(returncode=0, stdout='', stderr=''),  # bd init succeeds
            OSError("verify failed"),  # verify raises exception
        ]

        result = initialize_beads_repo(Path("/repo"))

        assert result is False


class TestMergeLockDeferral:
    """Test merge lock deferral in check_and_commit_main_repo."""

    def test_defers_cleanup_when_merge_active(self):
        """Test that cleanup is deferred when merge lock is active."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=True):
            # git status shows changes, auto-commit fails
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/module.py", stderr=""),
                Mock(returncode=0),  # git add --all
                Mock(returncode=1, stdout="", stderr="hook failed"),  # git commit fails
            ]

            result = check_and_commit_main_repo(repo_path, mock_logger)

            # Should return True (deferred)
            assert result is True
            mock_logger.log_orchestrator.assert_any_call(
                "Deferring cleanup due to active merge operation"
            )



class TestDetectConflictMarkerFiles:
    """Test _detect_conflict_marker_files function."""

    def test_returns_files_with_markers(self, tmp_path):
        """Dirty files containing conflict markers are returned."""
        conflict = tmp_path / "conflict.py"
        conflict.write_text("<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\n")
        clean = tmp_path / "clean.py"
        clean.write_text("no markers\n")

        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.return_value = (
                " M conflict.py\n M clean.py",
                {'other': [' M conflict.py', ' M clean.py'], 'beads': [], 'worktree': [], 'untracked': []},
            )
            result = _detect_conflict_marker_files(tmp_path)

        assert result == ["conflict.py"]

    def test_returns_empty_for_clean_files(self, tmp_path):
        """No conflict markers means empty result."""
        clean = tmp_path / "clean.py"
        clean.write_text("all good\n")

        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.return_value = (
                " M clean.py",
                {'other': [' M clean.py'], 'beads': [], 'worktree': [], 'untracked': []},
            )
            result = _detect_conflict_marker_files(tmp_path)

        assert result == []

    def test_skips_deleted_files(self, tmp_path):
        """Deleted files (status 'D') should be skipped."""
        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.return_value = (
                " D deleted.py",
                {'other': [' D deleted.py'], 'beads': [], 'worktree': [], 'untracked': []},
            )
            result = _detect_conflict_marker_files(tmp_path)

        assert result == []

    def test_handles_git_status_failure(self, tmp_path):
        """Returns empty list when git status fails."""
        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.side_effect = subprocess.CalledProcessError(128, "git")
            result = _detect_conflict_marker_files(tmp_path)

        assert result == []

    def test_handles_no_other_changes(self, tmp_path):
        """Returns empty when there are no 'other' changes."""
        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.return_value = (
                " M .beads/db.json",
                {'other': [], 'beads': [' M .beads/db.json'], 'worktree': [], 'untracked': []},
            )
            result = _detect_conflict_marker_files(tmp_path)

        assert result == []


class TestRestoreConflictedFiles:
    """Test _restore_conflicted_files function."""

    def test_restores_conflicted_files(self, tmp_path):
        """Files with conflict markers are restored via git checkout."""
        mock_logger = Mock()

        with patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=["conflict.py"]), \
             patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            result = _restore_conflicted_files(tmp_path, mock_logger)

        assert result is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["git", "checkout", "--", "conflict.py"]
        mock_logger.log_orchestrator.assert_any_call("Conflicted files restored to last committed version")

    def test_no_conflicted_files_returns_false(self, tmp_path):
        """Returns False when no files have conflict markers."""
        mock_logger = Mock()

        with patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]):
            result = _restore_conflicted_files(tmp_path, mock_logger)

        assert result is False

    def test_handles_checkout_failure(self, tmp_path):
        """Failures in individual file restores are handled gracefully."""
        mock_logger = Mock()

        with patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=["bad.py"]), \
             patch('subprocess.run', side_effect=subprocess.TimeoutExpired("git", 30)):
            result = _restore_conflicted_files(tmp_path, mock_logger)

        # Should return False because no file was actually restored
        assert result is False


class TestCleanupRetriesWithConflictMarkers:
    """Test _run_cleanup_retries uses merge-conflict agent when markers detected."""

    def test_uses_merge_agent_when_markers_present(self):
        """When conflict markers found, invoke_merge_conflict_cleanup_agent is used."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agents.cleanup_agents.invoke_merge_conflict_cleanup_agent') as mock_merge, \
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=["src/file.py"]), \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/file.py", stderr=""),
                Mock(returncode=0),
                Mock(returncode=1, stdout="", stderr="hook failed"),
            ]
            mock_merge.return_value = (True, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_merge.assert_called_once()
            # Verify cwd and unmerged_files passed correctly
            call_kwargs = mock_merge.call_args[1]
            assert call_kwargs['cwd'] == str(repo_path)
            assert call_kwargs['unmerged_files'] == ["src/file.py"]
            assert call_kwargs['wait_for_merge'] is False
            mock_cleanup.assert_not_called()

    def test_uses_generic_agent_when_no_markers(self):
        """Without conflict markers, generic invoke_cleanup_agent is used."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.agents.cleanup_agents.invoke_merge_conflict_cleanup_agent') as mock_merge, \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]), \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/file.py", stderr=""),
                Mock(returncode=0),
                Mock(returncode=1, stdout="", stderr="hook failed"),
            ]
            mock_cleanup.return_value = (True, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_cleanup.assert_called_once()
            # Verify cwd is passed to generic cleanup agent
            call_kw = mock_cleanup.call_args
            assert call_kw[1]['cwd'] == str(repo_path)
            assert call_kw[1]['wait_for_merge'] is False
            mock_merge.assert_not_called()

    def test_switches_agent_type_between_retries(self):
        """If markers are resolved mid-retry, agent type switches to generic."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agents.cleanup_agents.invoke_merge_conflict_cleanup_agent') as mock_merge, \
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files') as mock_detect, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check.time.sleep'):
            # First detection: markers present; re-detection between retries: markers gone
            mock_detect.side_effect = [["src/file.py"], []]
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/file.py", stderr=""),
                Mock(returncode=0),
                Mock(returncode=1, stdout="", stderr="hook failed"),
            ]
            mock_merge.return_value = (False, Mock())
            mock_cleanup.return_value = (True, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_merge.assert_called_once()
            mock_cleanup.assert_called_once()

    def test_restore_fallback_before_stash(self):
        """After cleanup retries fail, conflicted files are restored before stashing."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]), \
             patch('pokepoke.git.repo_check._restore_conflicted_files') as mock_restore, \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check._try_reset_working_tree', return_value=False), \
             patch('pokepoke.git.repo_check.time.sleep'):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/file.py", stderr=""),
                Mock(returncode=0),
                Mock(returncode=1, stdout="", stderr="hook failed"),
                Mock(returncode=0),
                Mock(returncode=0, stdout="", stderr=""),
            ]
            mock_cleanup.return_value = (False, Mock())
            mock_restore.return_value = False

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
            mock_restore.assert_called_once()

    def test_restore_success_retries_auto_commit(self):
        """When restore succeeds, auto-commit is retried."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent') as mock_cleanup, \
             patch('pokepoke.git.repo_check._detect_conflict_marker_files', return_value=[]), \
             patch('pokepoke.git.repo_check._restore_conflicted_files', return_value=True), \
             patch('pokepoke.git.repo_check.merge_lock_active', return_value=False), \
             patch('pokepoke.git.repo_check.time.sleep'):
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" M src/file.py", stderr=""),
                Mock(returncode=0),
                Mock(returncode=1, stdout="", stderr="hook failed"),
                Mock(returncode=0),
                Mock(returncode=0, stdout="", stderr=""),
            ]
            mock_cleanup.return_value = (False, Mock())

            result = check_and_commit_main_repo(repo_path, mock_logger)

            assert result is True
