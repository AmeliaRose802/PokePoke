"""Tests for custom maintenance agent lifecycle.

Covers custom agent creation, config persistence, prompt rendering with
placeholders, scheduler registration, and execution.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from pokepoke.config import (
    MaintenanceAgentConfig,
    MaintenanceConfig,
    ProjectConfig,
    load_config,
    reset_config,
)
from pokepoke.maintenance_scheduler import (
    MaintenanceScheduler,
    _PARALLEL_SAFE_AGENTS,
    _SINGLETON_AGENTS,
)
from pokepoke.prompts import PromptService
from pokepoke.types import AgentStats, SessionStats


@pytest.fixture(autouse=True)
def _clear_config():
    """Reset cached config around each test."""
    reset_config()
    yield
    reset_config()


# ── Custom agent config creation ─────────────────────────────────────────


class TestCustomAgentCreation:
    """Test creating custom maintenance agents via config."""

    def test_custom_agent_from_dict(self):
        """A custom agent defined in config dict is parsed correctly."""
        data = {
            "maintenance": {
                "agents": [
                    {
                        "name": "Janitor",
                        "prompt_file": "janitor.md",
                        "frequency": 3,
                        "needs_worktree": True,
                        "merge_changes": False,
                        "model": "gpt-5.1-codex",
                        "enabled": True,
                    }
                ]
            }
        }
        config = ProjectConfig.from_dict(data)
        assert len(config.maintenance.agents) == 1
        agent = config.maintenance.agents[0]
        assert agent.name == "Janitor"
        assert agent.prompt_file == "janitor.md"
        assert agent.frequency == 3
        assert agent.needs_worktree is True
        assert agent.merge_changes is False
        assert agent.model == "gpt-5.1-codex"
        assert agent.enabled is True

    def test_custom_agent_defaults(self):
        """Custom agent with minimal fields gets sensible defaults."""
        data = {
            "maintenance": {
                "agents": [
                    {"name": "Janitor", "prompt_file": "janitor.md"}
                ]
            }
        }
        config = ProjectConfig.from_dict(data)
        agent = config.maintenance.agents[0]
        assert agent.frequency == 5
        assert agent.needs_worktree is False
        assert agent.merge_changes is True
        assert agent.model is None
        assert agent.enabled is True

    def test_multiple_custom_agents(self):
        """Multiple custom agents can coexist in config."""
        data = {
            "maintenance": {
                "agents": [
                    {"name": "Janitor", "prompt_file": "janitor.md", "frequency": 2},
                    {"name": "Linter", "prompt_file": "linter.md", "frequency": 4},
                    {"name": "Formatter", "prompt_file": "formatter.md", "frequency": 6},
                ]
            }
        }
        config = ProjectConfig.from_dict(data)
        names = [a.name for a in config.maintenance.agents]
        assert names == ["Janitor", "Linter", "Formatter"]

    def test_custom_agents_replace_defaults(self):
        """Custom agents list replaces the built-in defaults entirely."""
        data = {
            "maintenance": {
                "agents": [
                    {"name": "OnlyOne", "prompt_file": "only.md", "frequency": 1}
                ]
            }
        }
        config = ProjectConfig.from_dict(data)
        assert len(config.maintenance.agents) == 1
        assert config.maintenance.agents[0].name == "OnlyOne"

    def test_disabled_custom_agent(self):
        """A custom agent can be disabled via config."""
        data = {
            "maintenance": {
                "agents": [
                    {"name": "Janitor", "prompt_file": "janitor.md", "enabled": False}
                ]
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.maintenance.agents[0].enabled is False


# ── Config persistence (YAML round-trip) ─────────────────────────────────


class TestCustomAgentConfigPersistence:
    """Test that custom agent config round-trips through YAML."""

    def test_yaml_round_trip(self, tmp_path):
        """Config saved to YAML and reloaded produces the same agent list."""
        agents = [
            {
                "name": "Janitor",
                "prompt_file": "janitor.md",
                "frequency": 3,
                "needs_worktree": True,
                "merge_changes": False,
                "model": "gpt-5.1-codex",
                "enabled": True,
            },
            {
                "name": "Formatter",
                "prompt_file": "formatter.md",
                "frequency": 7,
                "needs_worktree": False,
                "merge_changes": True,
                "model": None,
                "enabled": True,
            },
        ]
        config_data = {"project_name": "TestProject", "maintenance": {"agents": agents}}

        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(config_data), encoding="utf-8")

        config = load_config(config_path=config_file)
        assert config.project_name == "TestProject"
        assert len(config.maintenance.agents) == 2

        a0 = config.maintenance.agents[0]
        assert a0.name == "Janitor"
        assert a0.frequency == 3
        assert a0.needs_worktree is True
        assert a0.merge_changes is False
        assert a0.model == "gpt-5.1-codex"

        a1 = config.maintenance.agents[1]
        assert a1.name == "Formatter"
        assert a1.frequency == 7
        assert a1.model is None

    def test_json_round_trip(self, tmp_path):
        """Config saved to JSON and reloaded produces the same agent list."""
        config_data = {
            "maintenance": {
                "agents": [
                    {"name": "Janitor", "prompt_file": "janitor.md", "frequency": 4}
                ]
            }
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        config = load_config(config_path=config_file)
        assert len(config.maintenance.agents) == 1
        assert config.maintenance.agents[0].name == "Janitor"
        assert config.maintenance.agents[0].frequency == 4

    def test_empty_agents_list_persists(self, tmp_path):
        """An empty agents list removes all maintenance agents."""
        config_data = {"maintenance": {"agents": []}}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config_data), encoding="utf-8")

        config = load_config(config_path=config_file)
        assert len(config.maintenance.agents) == 0


# ── Prompt rendering with template placeholders ──────────────────────────


class TestCustomAgentPromptRendering:
    """Test prompt rendering for custom agent templates."""

    def test_render_custom_prompt_with_placeholders(self, tmp_path):
        """Custom prompt template renders all standard placeholders."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()

        template = (
            "Agent: {{agent_name}}\n"
            "Repo: {{repo_root}}\n"
            "Branch: {{branch_name}}\n"
            "Items completed: {{item_count}}\n"
            "Project: {{project_name}}\n"
            "Timestamp: {{timestamp}}\n"
        )
        (user_dir / "janitor.md").write_text(template, encoding="utf-8")

        service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
        rendered = service.load_and_render("janitor", {
            "agent_name": "Janitor",
            "repo_root": "/home/user/project",
            "branch_name": "main",
            "item_count": "42",
            "project_name": "PokePoke",
            "timestamp": "2026-02-22T00:00:00Z",
        })

        assert "Agent: Janitor" in rendered
        assert "Repo: /home/user/project" in rendered
        assert "Branch: main" in rendered
        assert "Items completed: 42" in rendered
        assert "Project: PokePoke" in rendered
        assert "Timestamp: 2026-02-22T00:00:00Z" in rendered

    def test_missing_placeholder_marked(self, tmp_path):
        """Unset placeholders produce {{missing:name}} markers."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        (user_dir / "test.md").write_text(
            "Hello {{agent_name}} on {{branch_name}}",
            encoding="utf-8",
        )

        service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
        rendered = service.load_and_render("test", {"agent_name": "Janitor"})

        assert "Hello Janitor" in rendered
        assert "{{missing:branch_name}}" in rendered

    def test_conditional_section_in_custom_prompt(self, tmp_path):
        """Conditional sections render correctly in custom prompts."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        (user_dir / "cond.md").write_text(
            "Start\n{{#needs_cleanup}}Do cleanup{{/needs_cleanup}}\nEnd",
            encoding="utf-8",
        )

        service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)

        shown = service.load_and_render("cond", {"needs_cleanup": True})
        assert "Do cleanup" in shown

        hidden = service.load_and_render("cond", {"needs_cleanup": False})
        assert "Do cleanup" not in hidden

    def test_metadata_extracts_custom_placeholders(self, tmp_path):
        """get_prompt_metadata lists template variables from custom prompt."""
        user_dir = tmp_path / "user"
        user_dir.mkdir()
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        (user_dir / "custom.md").write_text(
            "{{repo_root}} {{agent_name}} {{branch_name}} {{item_count}}",
            encoding="utf-8",
        )

        service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)
        meta = service.get_prompt_metadata("custom")

        expected_vars = {"agent_name", "branch_name", "item_count", "repo_root"}
        assert expected_vars.issubset(set(meta["template_variables"]))

    def test_custom_prompt_saved_to_user_dir(self, tmp_path):
        """Saving a custom prompt persists it to the user prompts directory."""
        user_dir = tmp_path / "user"
        builtin_dir = tmp_path / "builtin"
        builtin_dir.mkdir()
        (builtin_dir / "placeholder.md").write_text("ok", encoding="utf-8")

        service = PromptService(prompts_dir=user_dir, builtin_dir=builtin_dir)

        content = "Custom prompt for {{agent_name}}"
        result = service.save_prompt("janitor", content)

        assert result["saved"]
        assert (user_dir / "janitor.md").read_text(encoding="utf-8") == content

    def test_beads_item_prompt_renders(self):
        """The beads-item prompt template renders with standard variables."""
        service = PromptService()
        rendered = service.load_and_render("beads-item", {
            "item_id": "PokePoke-abc",
            "title": "Fix stuff",
            "description": "Fix the broken stuff",
            "issue_type": "task",
            "priority": "2",
            "labels": "tests, maintenance",
            "command_timeout": "300",
        })
        assert "PokePoke-abc" in rendered
        assert "Fix stuff" in rendered
        assert "tests, maintenance" in rendered


# ── Scheduler registration & execution ───────────────────────────────────


class TestCustomAgentSchedulerRegistration:
    """Test that custom agents are registered with and executed by the scheduler."""

    def setup_method(self):
        """Reset the global scheduler singleton."""
        import pokepoke.maintenance_scheduler as ms
        ms._scheduler = None

    @patch("pokepoke.maintenance_scheduler.get_active_agent_count", return_value=0)
    @patch("pokepoke.shutdown.should_stop_after_current", return_value=False)
    @patch("pokepoke.maintenance_scheduler.try_lock")
    @patch("pokepoke.maintenance_scheduler.get_config")
    @patch("pokepoke.maintenance_scheduler.run_maintenance_agent")
    @patch("pokepoke.maintenance_scheduler._run_special_agent")
    @patch("pokepoke.maintenance_scheduler.set_terminal_banner")
    @patch("pokepoke.terminal_ui.ui")
    def test_custom_agent_runs_at_frequency(
        self, mock_ui, mock_banner, mock_special, mock_run, mock_config, mock_lock,
        mock_stop, mock_active,
    ):
        """A custom agent runs when items_completed hits its frequency."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Janitor",
                prompt_file="janitor.md",
                frequency=3,
                needs_worktree=True,
                merge_changes=False,
            ),
        ])
        mock_config.return_value = config
        mock_lock.return_value = Mock()
        mock_run.return_value = AgentStats(input_tokens=50)

        from pokepoke.maintenance_scheduler import run_periodic_maintenance
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        # Not due at 2
        run_periodic_maintenance(2, session_stats, run_logger)
        mock_run.assert_not_called()

        # Due at 3
        run_periodic_maintenance(3, session_stats, run_logger)
        calls = [c for c in mock_run.call_args_list if c[0][0] == "Janitor"]
        assert len(calls) == 1
        assert calls[0][1]["needs_worktree"] is True
        assert calls[0][1]["merge_changes"] is False

    @patch("pokepoke.maintenance_scheduler.try_lock")
    @patch("pokepoke.maintenance_scheduler.get_config")
    @patch("pokepoke.maintenance_scheduler.run_maintenance_agent")
    @patch("pokepoke.maintenance_scheduler._run_special_agent")
    @patch("pokepoke.maintenance_scheduler.set_terminal_banner")
    @patch("pokepoke.terminal_ui.ui")
    def test_disabled_custom_agent_skipped(
        self, mock_ui, mock_banner, mock_special, mock_run, mock_config, mock_lock
    ):
        """A disabled custom agent is never executed."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Janitor", prompt_file="janitor.md",
                frequency=1, enabled=False,
            ),
        ])
        mock_config.return_value = config
        mock_lock.return_value = Mock()

        from pokepoke.maintenance_scheduler import run_periodic_maintenance
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        run_periodic_maintenance(1, session_stats, run_logger)
        mock_run.assert_not_called()
        mock_special.assert_not_called()

    @patch("pokepoke.maintenance_scheduler.get_active_agent_count", return_value=0)
    @patch("pokepoke.shutdown.should_stop_after_current", return_value=False)
    @patch("pokepoke.maintenance_scheduler.try_lock")
    @patch("pokepoke.maintenance_scheduler.get_config")
    @patch("pokepoke.maintenance_scheduler.run_maintenance_agent")
    @patch("pokepoke.maintenance_scheduler._run_special_agent")
    @patch("pokepoke.maintenance_scheduler.set_terminal_banner")
    @patch("pokepoke.terminal_ui.ui")
    def test_custom_agent_model_override_passed(
        self, mock_ui, mock_banner, mock_special, mock_run, mock_config, mock_lock,
        mock_stop, mock_active,
    ):
        """Custom agent's model override is forwarded to run_maintenance_agent."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Janitor",
                prompt_file="janitor.md",
                frequency=1,
                model="claude-sonnet-4.5",
            ),
        ])
        mock_config.return_value = config
        mock_lock.return_value = Mock()
        mock_run.return_value = None

        from pokepoke.maintenance_scheduler import run_periodic_maintenance
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        run_periodic_maintenance(1, session_stats, run_logger)

        calls = [c for c in mock_run.call_args_list if c[0][0] == "Janitor"]
        assert len(calls) == 1
        assert calls[0][1]["model"] == "claude-sonnet-4.5"

    def test_unknown_custom_agent_gets_singleton_guard(self):
        """Custom agents not in classification sets get singleton protection."""
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        unknown_cfg = MaintenanceAgentConfig(
            name="My Custom Bot", prompt_file="custom-bot.md", frequency=1,
        )

        assert "My Custom Bot" not in _SINGLETON_AGENTS
        assert "My Custom Bot" not in _PARALLEL_SAFE_AGENTS

        with patch("pokepoke.maintenance_scheduler.try_lock") as mock_lock, \
             patch.object(scheduler, "_run_agent_with_coordination") as mock_coord:
            mock_lock.return_value = Mock()
            scheduler._maybe_run_agent(
                "My Custom Bot", unknown_cfg, Mock(), session_stats, run_logger
            )
            run_logger.log_maintenance.assert_any_call(
                "my_custom_bot",
                "WARNING: Unknown agent classification for My Custom Bot, applying singleton guard",
            )
            mock_coord.assert_called_once()


# ── Custom agent execution and stats ─────────────────────────────────────


class TestCustomAgentExecution:
    """Test execution path for custom agents through the scheduler."""

    @patch("pokepoke.maintenance_scheduler.set_terminal_banner")
    @patch("pokepoke.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance_scheduler.run_maintenance_agent")
    def test_custom_agent_uses_generic_runner(
        self, mock_run, mock_ui, mock_banner
    ):
        """Custom agents (non-special) go through run_maintenance_agent."""
        mock_run.return_value = AgentStats(input_tokens=200)

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(
            name="Janitor",
            prompt_file="janitor.md",
            frequency=2,
            needs_worktree=True,
            merge_changes=True,
            model="claude-opus-4.6",
        )
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        scheduler._run_agent_with_coordination(
            "Janitor", agent_cfg, Path("/repo"), session_stats, run_logger
        )

        mock_run.assert_called_once_with(
            "Janitor",
            "janitor.md",
            repo_root=Path("/repo"),
            needs_worktree=True,
            merge_changes=True,
            model="claude-opus-4.6",
            item_logger=run_logger.start_maintenance_log.return_value,
            parent_agent_id="maintenance-janitor",
        )

    @patch("pokepoke.maintenance_scheduler.set_terminal_banner")
    @patch("pokepoke.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance_scheduler.run_maintenance_agent")
    def test_custom_agent_stats_aggregated(
        self, mock_run, mock_ui, mock_banner
    ):
        """Stats from a successful custom agent run are aggregated into session stats."""
        mock_run.return_value = AgentStats(
            wall_duration=15.0, input_tokens=300, lines_added=10
        )

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(
            name="Janitor", prompt_file="janitor.md", frequency=2,
        )
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        scheduler._run_agent_with_coordination(
            "Janitor", agent_cfg, Path("/repo"), session_stats, run_logger
        )

        assert session_stats.agent_stats.wall_duration == 15.0
        assert session_stats.agent_stats.input_tokens == 300
        assert session_stats.agent_stats.lines_added == 10
        assert session_stats.janitor_agent_runs == 1

    @patch("pokepoke.maintenance_scheduler.set_terminal_banner")
    @patch("pokepoke.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance_scheduler.run_maintenance_agent")
    def test_custom_agent_failure_logged(
        self, mock_run, mock_ui, mock_banner
    ):
        """A custom agent returning None is logged as failed."""
        mock_run.return_value = None

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(
            name="Janitor", prompt_file="janitor.md", frequency=2,
        )
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        scheduler._run_agent_with_coordination(
            "Janitor", agent_cfg, Path("/repo"), session_stats, run_logger
        )

        run_logger.log_maintenance.assert_any_call("janitor", "Janitor Agent failed")

    @patch("pokepoke.maintenance_scheduler.set_terminal_banner")
    @patch("pokepoke.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance_scheduler.run_maintenance_agent")
    def test_custom_agent_exception_is_swallowed(
        self, mock_run, mock_ui, mock_banner
    ):
        """An exception during custom agent run is caught and logged, not re-raised."""
        mock_run.side_effect = RuntimeError("boom")

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(
            name="Janitor", prompt_file="janitor.md", frequency=2,
        )
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        # Exception should NOT propagate (PokePoke-5arw regression fix)
        scheduler._run_agent_with_coordination(
            "Janitor", agent_cfg, Path("/repo"), session_stats, run_logger
        )

        # Exception should be logged
        run_logger.log_maintenance.assert_any_call("janitor", "Janitor Agent raised exception")
