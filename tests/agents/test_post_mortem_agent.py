"""Tests for post_mortem_agent module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.agents.post_mortem_agent import PostMortemAgent, run_post_mortem_agent
from pokepoke.agents.post_mortem_analyzer import FailurePattern
from pokepoke.config import PostMortemConfig, ProjectConfig
from pokepoke.types import BeadsWorkItem, SessionStats


def _make_config(enabled: bool = True, **overrides) -> ProjectConfig:
    pm_kwargs = {"enabled": enabled}
    pm_kwargs.update(overrides)
    return ProjectConfig(post_mortem=PostMortemConfig(**pm_kwargs))


def _make_pattern(**kwargs) -> FailurePattern:
    defaults = {
        "pattern_type": "tool_timeout",
        "description": "Tools timing out",
        "affected_items": ["task-1"],
        "frequency": 3,
        "severity": "P1",
        "sample_logs": ["log sample"],
        "suggested_fix": "increase timeout",
        "root_cause": "slow network",
    }
    defaults.update(kwargs)
    return FailurePattern(**defaults)


def _make_work_item(item_id: str = "pm-1", title: str = "Fix timeout") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title=title,
        status="ready",
        priority=1,
        issue_type="bug",
    )


class TestPostMortemAgentInit:
    """Tests for PostMortemAgent initialization."""

    def test_init_defaults(self):
        with patch("pokepoke.agents.post_mortem_agent.load_config") as mock_load:
            mock_load.return_value = _make_config()
            agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"))
        assert agent.run_logs_dir == Path("/fake/logs")
        assert agent.run_logger is None
        assert agent.patterns == []
        assert agent.created_item_ids == []

    def test_init_with_explicit_config(self):
        config = _make_config(enabled=False)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        assert agent.config is config

    def test_init_with_run_logger(self):
        config = _make_config()
        mock_logger = MagicMock()
        agent = PostMortemAgent(
            run_logs_dir=Path("/fake/logs"),
            config=config,
            run_logger=mock_logger,
        )
        assert agent.run_logger is mock_logger


class TestPostMortemAgentDisabled:
    """Tests for when post-mortem is disabled."""

    def test_run_disabled(self):
        config = _make_config(enabled=False)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        result = agent.run()
        assert result["enabled"] is False
        assert result["patterns_found"] == 0
        assert result["items_created"] == 0


class TestPostMortemAgentAnalysis:
    """Tests for the analysis phase."""

    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_no_patterns_found(self, mock_analyzer_cls):
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = []
        mock_analyzer_cls.return_value = mock_analyzer

        config = _make_config()
        run_logger = MagicMock()
        agent = PostMortemAgent(
            run_logs_dir=Path("/fake/logs"), config=config, run_logger=run_logger
        )
        result = agent.run()
        assert result["enabled"] is True
        assert result["patterns_found"] == 0
        assert result["items_created"] == 0

    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_patterns_found_no_items_created(self, mock_analyzer_cls, mock_creator_cls):
        patterns = [_make_pattern()]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "1 pattern found"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = []
        mock_creator_cls.return_value = mock_creator

        config = _make_config()
        run_logger = MagicMock()
        agent = PostMortemAgent(
            run_logs_dir=Path("/fake/logs"), config=config, run_logger=run_logger
        )
        result = agent.run()
        assert result["enabled"] is True
        assert result["patterns_found"] == 1
        assert result["items_created"] == 0
        assert result["items_fixed"] == 0

    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_patterns_limited_to_max_items(self, mock_analyzer_cls, mock_creator_cls):
        patterns = [_make_pattern(pattern_type=f"type_{i}") for i in range(10)]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "10 patterns"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = []
        mock_creator_cls.return_value = mock_creator

        config = _make_config(max_items=3)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        agent.run()
        # Should only pass first 3 patterns to file_issues
        call_args = mock_creator.file_issues.call_args[0][0]
        assert len(call_args) == 3


class TestPostMortemAgentSelfHealing:
    """Tests for self-healing phase."""

    @patch("pokepoke.agents.post_mortem_agent.process_work_item")
    @patch("pokepoke.agents.post_mortem_agent.get_ready_work_items")
    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_self_healing_success(
        self, mock_analyzer_cls, mock_creator_cls, mock_ready, mock_process
    ):
        patterns = [_make_pattern()]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "1 pattern"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = ["pm-1"]
        mock_creator_cls.return_value = mock_creator

        ready_item = _make_work_item("pm-1")
        mock_ready.return_value = [ready_item]

        mock_result = MagicMock()
        mock_result.success = True
        mock_process.return_value = mock_result

        config = _make_config(timeout_minutes=60)
        session_stats = MagicMock(spec=SessionStats)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        result = agent.run(session_stats=session_stats)

        assert result["items_created"] == 1
        assert result["items_fixed"] == 1
        session_stats.record_completion.assert_called_once()

    @patch("pokepoke.agents.post_mortem_agent.process_work_item")
    @patch("pokepoke.agents.post_mortem_agent.get_ready_work_items")
    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_self_healing_failure(
        self, mock_analyzer_cls, mock_creator_cls, mock_ready, mock_process
    ):
        patterns = [_make_pattern()]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "1 pattern"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = ["pm-1"]
        mock_creator_cls.return_value = mock_creator

        ready_item = _make_work_item("pm-1")
        mock_ready.return_value = [ready_item]

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.failure_reason = "test failure"
        mock_process.return_value = mock_result

        config = _make_config(timeout_minutes=60)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        result = agent.run()

        assert result["items_created"] == 1
        assert result["items_fixed"] == 0

    @patch("pokepoke.agents.post_mortem_agent.get_ready_work_items")
    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_self_healing_no_ready_items(
        self, mock_analyzer_cls, mock_creator_cls, mock_ready
    ):
        patterns = [_make_pattern()]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "1 pattern"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = ["pm-1"]
        mock_creator_cls.return_value = mock_creator

        mock_ready.return_value = []  # No items ready

        config = _make_config(timeout_minutes=60)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        result = agent.run()

        assert result["items_created"] == 1
        assert result["items_fixed"] == 0

    @patch("pokepoke.agents.post_mortem_agent.get_ready_work_items")
    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_self_healing_ready_returns_none(
        self, mock_analyzer_cls, mock_creator_cls, mock_ready
    ):
        patterns = [_make_pattern()]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "1 pattern"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = ["pm-1"]
        mock_creator_cls.return_value = mock_creator

        mock_ready.return_value = None

        config = _make_config(timeout_minutes=60)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        result = agent.run()
        assert result["items_fixed"] == 0

    @patch("pokepoke.agents.post_mortem_agent.process_work_item")
    @patch("pokepoke.agents.post_mortem_agent.get_ready_work_items")
    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_self_healing_exception(
        self, mock_analyzer_cls, mock_creator_cls, mock_ready, mock_process
    ):
        patterns = [_make_pattern()]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "1 pattern"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = ["pm-1"]
        mock_creator_cls.return_value = mock_creator

        ready_item = _make_work_item("pm-1")
        mock_ready.return_value = [ready_item]
        mock_process.side_effect = RuntimeError("boom")

        config = _make_config(timeout_minutes=60)
        run_logger = MagicMock()
        agent = PostMortemAgent(
            run_logs_dir=Path("/fake/logs"), config=config, run_logger=run_logger
        )
        result = agent.run()
        assert result["items_fixed"] == 0

    @patch("pokepoke.agents.post_mortem_agent.BeadsIssueCreator")
    @patch("pokepoke.agents.post_mortem_agent.LogAnalyzer")
    def test_timeout_skips_self_healing(self, mock_analyzer_cls, mock_creator_cls):
        patterns = [_make_pattern()]
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = patterns
        mock_analyzer.get_summary.return_value = "1 pattern"
        mock_analyzer_cls.return_value = mock_analyzer

        mock_creator = MagicMock()
        mock_creator.file_issues.return_value = ["pm-1"]
        mock_creator_cls.return_value = mock_creator

        # Very short timeout so self-healing is skipped
        config = _make_config(timeout_minutes=0)
        agent = PostMortemAgent(run_logs_dir=Path("/fake/logs"), config=config)
        result = agent.run()
        assert result.get("timeout_reached") is True
        assert result["items_fixed"] == 0


class TestRunPostMortemAgent:
    """Tests for the convenience function."""

    @patch("pokepoke.agents.post_mortem_agent.load_config")
    def test_convenience_function_disabled(self, mock_load):
        mock_load.return_value = _make_config(enabled=False)
        result = run_post_mortem_agent(run_logs_dir=Path("/fake/logs"))
        assert result["enabled"] is False

    def test_convenience_function_with_all_params(self):
        config = _make_config(enabled=False)
        result = run_post_mortem_agent(
            run_logs_dir=Path("/fake/logs"),
            config=config,
            run_logger=MagicMock(),
            session_stats=MagicMock(),
        )
        assert result["enabled"] is False
