"""Unit tests for orchestrator validation and repository state checking."""

from unittest.mock import Mock, patch

from pokepoke.git.repo_check import check_and_commit_main_repo
from pokepoke.orchestration.orchestrator import run_orchestrator
from pokepoke.types import AgentStats, BeadsStats
from tests.orchestration.conftest import make_orchestrator_mocks


class TestCheckMainRepoReadyForMerge:
    """Test check_main_repo_ready_for_merge function."""

    @patch('subprocess.run')
    def test_clean_repo(self, mock_subprocess: Mock) -> None:
        """Test clean repo returns ready."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        mock_subprocess.return_value = Mock(stdout="")
        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is True
        assert error == ""

    @patch('subprocess.run')
    def test_beads_only_changes(self, mock_subprocess: Mock) -> None:
        """Test beads-only changes are auto-committed."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        # First call returns beads changes, subsequent calls succeed
        mock_subprocess.side_effect = [
            Mock(stdout="M .beads/issues.jsonl\n"),
            None,  # git add
            None   # git commit
        ]

        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is True
        assert error == ""
        assert mock_subprocess.call_count == 3

    @patch('subprocess.run')
    def test_non_beads_changes(self, mock_subprocess: Mock) -> None:
        """Test non-beads changes cause failure."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        mock_subprocess.return_value = Mock(stdout="M src/file.py\nM .beads/issues.jsonl\n")
        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is False
        assert "src/file.py" in error
        # Should only call git status once, not attempt to commit
        assert mock_subprocess.call_count == 1

    @patch('subprocess.run')
    def test_subprocess_error(self, mock_subprocess: Mock) -> None:
        """Test subprocess error is handled."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        mock_subprocess.side_effect = Exception("git command failed")
        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is False
        assert "git command failed" in error


class TestCheckAndCommitMainRepo:
    """Test check_and_commit_main_repo function."""

    @patch('pokepoke.git.repo_check.cleanup_lock')
    @patch('pokepoke.git.repo_check.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('subprocess.run')
    def test_check_and_commit_main_repo_with_non_beads_changes(
        self,
        mock_subprocess: Mock,
        mock_cleanup: Mock,
        _mock_merge_lock: Mock,
        mock_cleanup_lock: Mock,
    ) -> None:
        """Test check_and_commit_main_repo with non-beads changes - tries auto-commit first, then cleanup agent."""
        import tempfile
        from contextlib import contextmanager
        from pathlib import Path

        from pokepoke.utils.logging_utils import RunLogger

        # Make cleanup_lock() a no-op context manager
        @contextmanager
        def _noop_lock():
            yield
        mock_cleanup_lock.return_value = _noop_lock()

        # git status returns changes, auto-commit (add succeeds, commit fails),
        # reset attempt (checkout succeeds but files still dirty), then cleanup agent
        mock_subprocess.side_effect = [
            Mock(stdout=" M src/file.py\n M tests/test.py\n", returncode=0),  # git status
            Mock(returncode=0),  # git add --all (auto-commit)
            Mock(returncode=1, stdout="", stderr="pre-commit hook failed"),  # git commit fails
            Mock(returncode=0),  # git checkout -- . (reset working tree)
            Mock(stdout=" M src/file.py\n", returncode=0),  # git status after reset (still dirty)
            Mock(stdout="", returncode=0),  # git status --porcelain (conflict detection)
        ]
        # Mock cleanup agent to return success
        mock_cleanup.return_value = (True, AgentStats(
            wall_duration=1.0,
            api_duration=1.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=5,
            lines_removed=3,
            premium_requests=1
        ))

        # Create a temporary logger
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(base_dir=tmpdir)
            repo_path = Path.cwd()

            try:
                result = check_and_commit_main_repo(repo_path, run_logger)

                assert result is True  # Should return True after successful cleanup
                # Should call subprocess for git status + auto-commit attempt
                assert mock_subprocess.call_count >= 3
                mock_cleanup.assert_called_once()

                # Verify cleanup agent was called with correct work item
                call_args = mock_cleanup.call_args
                work_item = call_args[0][0]  # First positional argument
                assert work_item.id == "cleanup-main-repo-1"  # First attempt
                assert "uncommitted changes" in work_item.title.lower()
            finally:
                run_logger.close()


class TestCheckBeadsAvailable:
    """Test check_beads_available function."""

    @patch('pokepoke.git.repo_check.shutil.which', return_value=None)
    def test_bd_not_installed(self, mock_which: Mock) -> None:
        """Test returns False when bd command not found."""
        from pokepoke.git.repo_check import check_beads_available

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_succeeds(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns True when bd is installed and .beads directory initialized."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "config.yaml").write_text("test: true")

        result = check_beads_available()

        assert result is True

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_not_initialized(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns False when .beads directory doesn't exist."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_timeout(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns False when .beads directory exists but has no marker files."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".beads").mkdir()

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_exception(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns False when .beads directory is incomplete."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "random.txt").write_text("not a marker")

        result = check_beads_available()

        assert result is False


class TestRunOrchestratorRepoCheckFailure:
    """Test run_orchestrator when main repo check fails."""

    def test_repo_check_failure_returns_1(self) -> None:
        """Test orchestrator returns 1 when repo check fails."""
        with make_orchestrator_mocks(include_check_repo=True) as mocks:
            mocks['check_repo'].return_value = False

            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 1
            mocks['get_items'].assert_not_called()

    def test_repo_check_failure(self) -> None:
        """Test repo check failure returns 1."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        with make_orchestrator_mocks(include_check_repo=True) as mocks:
            mocks['check_repo'].return_value = False

            result = run_orch(interactive=False, continuous=False)
            assert result == 1


class TestOrchestratorCleanupDetection:
    """Test orchestrator's main repo cleanup detection."""

    @patch('subprocess.run')
    @patch('pokepoke.orchestration.orchestrator.check_and_commit_main_repo')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.get_ready_work_items')
    def test_detects_uncommitted_changes_and_invokes_cleanup(
        self,
        mock_get_items: Mock,
        mock_beads_stats: Mock,
        mock_check_repo: Mock,
        mock_subprocess: Mock,
    ) -> None:
        """Test that orchestrator invokes check_and_commit_main_repo."""
        mock_check_repo.return_value = True  # Repo check passes (cleanup succeeded or continued)
        mock_get_items.return_value = []  # No work items available
        mock_beads_stats.return_value = BeadsStats(
            total_issues=0, open_issues=0, in_progress_issues=0,
            closed_issues=0, ready_issues=0
        )

        with patch('pokepoke.orchestration.orchestrator.is_shutting_down', return_value=False):
            result = run_orchestrator(interactive=False, continuous=False)

        # Should return 0 because repo check passes
        assert result == 0
        # Should call check_and_commit_main_repo at least once
        mock_check_repo.assert_called()
        # Should call get_items since repo check passed
        mock_get_items.assert_called()

    @patch('subprocess.run')
    @patch('pokepoke.orchestration.orchestrator.check_and_commit_main_repo')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.get_ready_work_items')
    def test_detects_beads_changes_without_autocommit(
        self,
        mock_get_items: Mock,
        mock_beads_stats: Mock,
        mock_check_repo: Mock,
        mock_subprocess: Mock,
    ) -> None:
        """Test that beads-only changes are detected but NOT auto-committed."""
        mock_beads_stats.return_value = BeadsStats(
            total_issues=10,
            open_issues=5,
            in_progress_issues=2,
            closed_issues=3,
            ready_issues=1
        )
        mock_check_repo.return_value = True
        mock_get_items.return_value = []

        with patch('pokepoke.orchestration.orchestrator.is_shutting_down', return_value=False):
            result = run_orchestrator(interactive=False, continuous=False)

        mock_check_repo.assert_called_once()
        assert result == 0

    @patch('pokepoke.orchestration.orchestrator.get_ready_work_items')
    @patch('subprocess.run')
    def test_clean_repo_proceeds_to_work(
        self,
        mock_subprocess: Mock,
        mock_get_items: Mock,
    ) -> None:
        """Test that clean repo proceeds to normal work processing."""
        mock_subprocess.return_value = Mock(
            stdout="",
            returncode=0
        )
        mock_get_items.return_value = []

        result = run_orchestrator(interactive=False, continuous=False)

        mock_get_items.assert_called_once()
        assert result == 0
