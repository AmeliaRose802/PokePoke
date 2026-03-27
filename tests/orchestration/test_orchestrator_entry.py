"""Unit tests for orchestrator main entry point."""

from unittest.mock import Mock, patch


class TestOrchestratorMain:
    """Test main entry point."""

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_autonomous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with autonomous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=False,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--continuous'])
    def test_main_continuous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with continuous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=True,
            continuous=True,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--continuous'])
    def test_main_both_flags(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with both flags."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=True,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=False)
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_exits_when_beads_unavailable(self, mock_ui: Mock, _mock_ready: Mock) -> None:
        """Test main exits with code 1 when beads is not available."""
        from pokepoke.__main__ import main

        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 1

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke'])
    def test_main_interactive_initializes_beads_when_missing(
        self,
        mock_ui: Mock,
        mock_run: Mock,
        _mock_ready: Mock,
    ) -> None:
        """Test interactive main proceeds when project is ready."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=False)
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke'])
    def test_main_interactive_declines_beads_init_exits_1(
        self,
        mock_ui: Mock,
        _mock_ready: Mock,
    ) -> None:
        """Test interactive main exits when project is not ready."""
        from pokepoke.__main__ import main

        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 1

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--beta-first'])
    def test_main_beta_first(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with beta-first flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=False,
            run_beta_first=True,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.init.init_project', return_value=True)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init_success(self, mock_init: Mock) -> None:
        """Test main with --init flag succeeding."""
        from pokepoke.__main__ import main

        result = main()

        assert result == 0
        mock_init.assert_called_once()

    @patch('pokepoke.init.init_project', return_value=False)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init_failure(self, mock_init: Mock) -> None:
        """Test main with --init flag failing."""
        from pokepoke.__main__ import main

        result = main()

        assert result == 1

    @patch('sys.argv', ['pokepoke', '--repo', '/nonexistent/path/that/does/not/exist'])
    def test_main_repo_nonexistent(self) -> None:
        """Test main with --repo pointing to nonexistent path."""
        from pokepoke.__main__ import main
        result = main()
        assert result == 1

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    def test_main_repo_valid(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock, tmp_path) -> None:
        """Test main with --repo pointing to a valid directory."""
        import sys

        from pokepoke.__main__ import main
        with patch.object(sys, 'argv', ['pokepoke', '--autonomous', '--repo', str(tmp_path)]):
            mock_run.return_value = 0
            mock_ui.run_with_orchestrator.side_effect = lambda f: f()
            result = main()
        assert result == 0


class TestOrchestratorMainDuplicates:
    """Test main entry point (alternative test class)."""

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_autonomous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with autonomous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--beta-first'])
    def test_main_beta_first(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with beta-first flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=False,
            run_beta_first=True,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=False)
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_beads_unavailable(self, mock_ui: Mock, _mock_ready: Mock) -> None:
        """Test main returns 1 when project not ready."""
        from pokepoke.__main__ import main

        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 1

    @patch('pokepoke.init.init_project', return_value=True)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init(self, mock_init: Mock) -> None:
        """Test main with --init flag."""
        from pokepoke.__main__ import main

        result = main()
        assert result == 0

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--continuous'])
    def test_main_continuous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with continuous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=True,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )
