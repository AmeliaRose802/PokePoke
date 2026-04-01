"""Tests for beta_tester agent internals."""

import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.types import AgentStats

_BT = "pokepoke.agents.beta_tester"
_AR = "pokepoke.agents.agent_runner"


def _make_config(mcp_enabled=True, restart_script="scripts/Restart-MCPServer.ps1"):
    cfg = Mock()
    cfg.mcp_server.enabled = mcp_enabled
    cfg.mcp_server.restart_script = restart_script
    return cfg


def _setup_prompt(tmp_path):
    """Create a fake prompts dir with beta-tester.md."""
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "beta-tester.md").write_text("test prompt", encoding="utf-8")
    return prompt_dir


class TestRunBetaTesterMcpRestart:
    """Test MCP server restart paths inside run_beta_tester."""

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-001")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.subprocess")
    @patch(f"{_BT}.get_config")
    def test_mcp_restart_success(self, mock_config, mock_subprocess, mock_ui,
                                  mock_prompts_dir, mock_gen_id, mock_run_agent,
                                  tmp_path):
        """MCP restart with returncode=0 logs success."""
        import subprocess as real_subprocess

        import pokepoke.agents.beta_tester as bt_mod
        cfg = _make_config()
        mock_config.return_value = cfg

        # Create script at the path beta_tester.py will resolve
        package_root = Path(bt_mod.__file__).resolve().parent.parent.parent
        restart_path = package_root / cfg.mcp_server.restart_script
        restart_path.parent.mkdir(parents=True, exist_ok=True)
        created = not restart_path.exists()
        if created:
            restart_path.write_text("# dummy", encoding="utf-8")

        try:
            mock_subprocess.run.return_value = Mock(returncode=0, stdout="", stderr="")
            mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
            mock_prompts_dir.return_value = _setup_prompt(tmp_path)

            result = bt_mod.run_beta_tester(repo_root=tmp_path)

            assert result is not None
            mock_subprocess.run.assert_called_once()
        finally:
            if created and restart_path.exists():
                restart_path.unlink()

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-002")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.subprocess")
    @patch(f"{_BT}.get_config")
    def test_mcp_restart_nonzero_exit_with_output(self, mock_config, mock_subprocess,
                                                    mock_ui, mock_prompts_dir,
                                                    mock_gen_id, mock_run_agent,
                                                    tmp_path):
        """Non-zero exit with stdout logs warning."""
        import subprocess as real_subprocess

        import pokepoke.agents.beta_tester as bt_mod
        cfg = _make_config()
        mock_config.return_value = cfg

        package_root = Path(bt_mod.__file__).resolve().parent.parent.parent
        restart_path = package_root / cfg.mcp_server.restart_script
        restart_path.parent.mkdir(parents=True, exist_ok=True)
        created = not restart_path.exists()
        if created:
            restart_path.write_text("# dummy", encoding="utf-8")

        try:
            mock_subprocess.run.return_value = Mock(returncode=1, stdout="some output", stderr="")
            mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
            mock_prompts_dir.return_value = _setup_prompt(tmp_path)

            result = bt_mod.run_beta_tester(repo_root=tmp_path)

            assert result is not None
        finally:
            if created and restart_path.exists():
                restart_path.unlink()

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-007")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.subprocess")
    @patch(f"{_BT}.get_config")
    def test_mcp_restart_timeout(self, mock_config, mock_subprocess,
                                  mock_ui, mock_prompts_dir,
                                  mock_gen_id, mock_run_agent, tmp_path):
        """Timeout during restart logs warning and continues."""
        import subprocess as real_subprocess

        import pokepoke.agents.beta_tester as bt_mod
        cfg = _make_config()
        mock_config.return_value = cfg

        package_root = Path(bt_mod.__file__).resolve().parent.parent.parent
        restart_path = package_root / cfg.mcp_server.restart_script
        restart_path.parent.mkdir(parents=True, exist_ok=True)
        created = not restart_path.exists()
        if created:
            restart_path.write_text("# dummy", encoding="utf-8")

        try:
            mock_subprocess.run.side_effect = real_subprocess.TimeoutExpired("pwsh", 60)
            mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
            mock_prompts_dir.return_value = _setup_prompt(tmp_path)

            result = bt_mod.run_beta_tester(repo_root=tmp_path)

            assert result is not None
        finally:
            if created and restart_path.exists():
                restart_path.unlink()

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-008")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.subprocess")
    @patch(f"{_BT}.get_config")
    def test_mcp_restart_general_exception(self, mock_config, mock_subprocess,
                                            mock_ui, mock_prompts_dir,
                                            mock_gen_id, mock_run_agent, tmp_path):
        """General exception during restart logs warning and continues."""
        import subprocess as real_subprocess

        import pokepoke.agents.beta_tester as bt_mod
        cfg = _make_config()
        mock_config.return_value = cfg

        package_root = Path(bt_mod.__file__).resolve().parent.parent.parent
        restart_path = package_root / cfg.mcp_server.restart_script
        restart_path.parent.mkdir(parents=True, exist_ok=True)
        created = not restart_path.exists()
        if created:
            restart_path.write_text("# dummy", encoding="utf-8")

        try:
            mock_subprocess.run.side_effect = OSError("permission denied")
            mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
            mock_prompts_dir.return_value = _setup_prompt(tmp_path)

            result = bt_mod.run_beta_tester(repo_root=tmp_path)

            assert result is not None
        finally:
            if created and restart_path.exists():
                restart_path.unlink()

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-004")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.subprocess")
    @patch(f"{_BT}.get_config")
    def test_mcp_restart_script_not_found(self, mock_config, mock_subprocess,
                                           mock_ui, mock_prompts_dir,
                                           mock_gen_id, mock_run_agent, tmp_path):
        """Script not found logs warning (covers lines 41-42)."""
        cfg = _make_config(restart_script="nonexistent/Restart.ps1")
        mock_config.return_value = cfg
        mock_prompts_dir.return_value = _setup_prompt(tmp_path)

        from pokepoke.agents.beta_tester import run_beta_tester
        result = run_beta_tester(repo_root=tmp_path)

        assert result is not None

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-009")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.subprocess")
    @patch(f"{_BT}.get_config")
    def test_mcp_restart_rejects_path_traversal(self, mock_config, mock_subprocess,
                                                mock_ui, mock_prompts_dir,
                                                mock_gen_id, mock_run_agent, tmp_path,
                                                caplog):
        """Path traversal in restart_script is rejected and not executed."""
        import subprocess as real_subprocess

        import pokepoke.agents.beta_tester as bt_mod
        cfg = _make_config(restart_script="../evil.ps1")
        mock_config.return_value = cfg
        mock_subprocess.TimeoutExpired = real_subprocess.TimeoutExpired
        mock_prompts_dir.return_value = _setup_prompt(tmp_path)

        caplog.set_level(logging.WARNING)
        result = bt_mod.run_beta_tester(repo_root=tmp_path)

        assert result is not None
        mock_subprocess.run.assert_not_called()
        assert any(
            "escapes package root" in record.getMessage()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        )


class TestRunBetaTesterMcpDisabled:
    """Test MCP server disabled path."""

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-003")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.get_config")
    def test_mcp_not_enabled(self, mock_config, mock_ui, mock_prompts_dir,
                              mock_gen_id, mock_run_agent, tmp_path):
        """When MCP server is disabled, logs info (covers line 61)."""
        cfg = _make_config(mcp_enabled=False)
        mock_config.return_value = cfg
        mock_prompts_dir.return_value = _setup_prompt(tmp_path)

        from pokepoke.agents.beta_tester import run_beta_tester
        result = run_beta_tester(repo_root=tmp_path)

        assert result is not None


class TestRunBetaTesterPromptErrors:
    """Test prompt loading error paths."""

    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.get_config")
    def test_prompts_dir_not_found(self, mock_config, mock_prompts_dir, mock_ui):
        """FileNotFoundError returns None (covers lines 69-70)."""
        cfg = _make_config(mcp_enabled=False)
        mock_config.return_value = cfg
        mock_prompts_dir.side_effect = FileNotFoundError("prompts dir missing")

        from pokepoke.agents.beta_tester import run_beta_tester
        result = run_beta_tester()

        assert result is None

    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-005")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.get_config")
    def test_prompt_file_not_exists(self, mock_config, mock_prompts_dir,
                                     mock_ui, mock_gen_id, tmp_path):
        """Prompt file missing returns None (covers lines 73-75)."""
        cfg = _make_config(mcp_enabled=False)
        mock_config.return_value = cfg
        # Create prompts dir but NOT the beta-tester.md file
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        mock_prompts_dir.return_value = prompt_dir

        from pokepoke.agents.beta_tester import run_beta_tester
        result = run_beta_tester()

        assert result is None


class TestRunBetaTesterRepoRoot:
    """Test repo_root default path."""

    @patch(f"{_AR}._run_worktree_agent", return_value=AgentStats())
    @patch(f"{_AR}._generate_unique_agent_id", return_value="beta-test-006")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.get_config")
    def test_repo_root_defaults_to_cwd(self, mock_config, mock_ui,
                                        mock_prompts_dir, mock_gen_id,
                                        mock_run_agent, tmp_path):
        """repo_root=None uses Path.cwd() (covers line 89)."""
        cfg = _make_config(mcp_enabled=False)
        mock_config.return_value = cfg
        mock_prompts_dir.return_value = _setup_prompt(tmp_path)

        from pokepoke.agents.beta_tester import run_beta_tester
        result = run_beta_tester(repo_root=None)

        assert result is not None


class TestRunBetaTesterException:
    """Test exception propagation."""

    @patch(f"{_BT}.terminal_ui")
    @patch(f"{_BT}.get_pokepoke_prompts_dir")
    @patch(f"{_BT}.get_config")
    def test_unexpected_exception_propagates(self, mock_config, mock_prompts_dir, mock_ui):
        """Exceptions inside try block re-raised after logging (covers lines 100-103)."""
        cfg = _make_config(mcp_enabled=False)
        mock_config.return_value = cfg
        # Raise from get_pokepoke_prompts_dir with a non-FileNotFoundError
        mock_prompts_dir.side_effect = RuntimeError("unexpected crash")

        from pokepoke.agents.beta_tester import run_beta_tester
        with pytest.raises(RuntimeError, match="unexpected crash"):
            run_beta_tester()
