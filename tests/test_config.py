"""Tests for the project configuration system."""

import json
from unittest.mock import patch

import pytest

from pokepoke.config import (
    ProjectConfig,
    ModelConfig,
    ModelSyncConfig,
    MaintenanceConfig,
    MaintenanceAgentConfig,
    GitConfig,
    load_config,
    reset_config,
    get_config,
    _find_repo_root,  # noqa: F401  # used via patch strings
    _load_config_file,
)


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Clear config cache before and after each test."""
    reset_config()
    yield
    reset_config()


class TestModelConfig:
    """Tests for ModelConfig dataclass."""

    def test_defaults(self):
        config = ModelConfig()
        assert config.default == "claude-opus-4.6"
        assert config.fallback == "claude-sonnet-4.5"

    def test_custom_values(self):
        config = ModelConfig(default="gpt-4o", fallback="gpt-4o-mini")
        assert config.default == "gpt-4o"
        assert config.fallback == "gpt-4o-mini"


class TestMaintenanceAgentConfig:
    """Tests for MaintenanceAgentConfig dataclass."""

    def test_defaults(self):
        config = MaintenanceAgentConfig()
        assert config.name == ""
        assert config.prompt_file == ""
        assert config.frequency == 5
        assert config.needs_worktree is False
        assert config.merge_changes is True
        assert config.model is None
        assert config.enabled is True

    def test_custom_values(self):
        config = MaintenanceAgentConfig(
            name="Test Agent",
            prompt_file="test.md",
            frequency=3,
            needs_worktree=True,
            merge_changes=False,
            model="gpt-4o",
            enabled=False,
        )
        assert config.name == "Test Agent"
        assert config.frequency == 3
        assert config.model == "gpt-4o"
        assert config.enabled is False


class TestModelSyncConfig:
    """Tests for ModelSyncConfig dataclass."""

    def test_defaults(self):
        config = ModelSyncConfig()
        assert config.enabled is True
        assert config.interval_minutes == 60
        assert config.beta_only is True
        assert config.include_preview is True
        assert config.prune_unavailable is False
        assert config.create_beads_items is True
        assert config.issue_type == "task"
        assert config.priority == 2
        assert config.labels == ["model", "beta", "copilot"]

    def test_custom_values(self):
        config = ModelSyncConfig(
            enabled=False,
            interval_minutes=10,
            beta_only=False,
            include_preview=False,
            prune_unavailable=True,
            create_beads_items=False,
            issue_type="feature",
            priority=1,
            labels=["model", "experimental"],
        )
        assert config.enabled is False
        assert config.interval_minutes == 10
        assert config.beta_only is False
        assert config.include_preview is False
        assert config.prune_unavailable is True
        assert config.create_beads_items is False
        assert config.issue_type == "feature"
        assert config.priority == 1
        assert config.labels == ["model", "experimental"]


class TestMaintenanceConfig:
    """Tests for MaintenanceConfig dataclass."""

    def test_defaults_factory(self):
        config = MaintenanceConfig.defaults()
        assert len(config.agents) == 7
        names = [a.name for a in config.agents]
        assert "Tech Debt" in names
        assert "Janitor" in names
        assert "Beta Tester" in names
        assert "Code Review" in names
        assert "Worktree Cleanup" in names
        assert "Backlog Cleanup" in names
        assert "Model Sync" in names

    def test_default_frequencies(self):
        config = MaintenanceConfig.defaults()
        by_name = {a.name: a for a in config.agents}
        assert by_name["Tech Debt"].frequency == 5
        assert by_name["Janitor"].frequency == 2
        assert by_name["Backlog Cleanup"].frequency == 7
        assert by_name["Beta Tester"].frequency == 3
        assert by_name["Code Review"].frequency == 5
        assert by_name["Worktree Cleanup"].frequency == 4
        assert by_name["Model Sync"].frequency == 1

    def test_code_review_has_model(self):
        config = MaintenanceConfig.defaults()
        code_review = [a for a in config.agents if a.name == "Code Review"][0]
        assert code_review.model == "gpt-5.1-codex"


class TestGitConfig:
    """Tests for GitConfig dataclass."""

    def test_defaults(self):
        config = GitConfig()
        assert config.default_branch is None
        assert config.fallback_branch == "master"

    def test_get_preferred_branch_fallback(self):
        config = GitConfig()
        assert config.get_preferred_branch() == "master"

    def test_get_preferred_branch_explicit(self):
        config = GitConfig(default_branch="main")
        assert config.get_preferred_branch() == "main"

    def test_get_preferred_branch_custom_fallback(self):
        config = GitConfig(fallback_branch="develop")
        assert config.get_preferred_branch() == "develop"


class TestProjectConfig:
    """Tests for ProjectConfig dataclass."""

    def test_defaults(self):
        config = ProjectConfig()
        assert config.project_name == ""
        assert config.models.default == "claude-opus-4.6"
        assert config.ai_backend.provider == "copilot"
        assert config.ai_backend.copilot_cli_path == "copilot.cmd"
        assert config.model_sync.interval_minutes == 60
        assert config.mcp_server.enabled is False
        assert config.test_data == {}
        assert config.work_artifacts_dir is None

    def test_from_dict_empty(self):
        config = ProjectConfig.from_dict({})
        assert config.project_name == ""
        assert config.models.default == "claude-opus-4.6"

    def test_from_dict_full(self):
        data = {
            "project_name": "MyProject",
            "models": {
                "default": "gpt-4o",
                "fallback": "gpt-4o-mini",
            },
            "ai_backend": {
                "provider": "claude-code",
                "copilot_cli_path": "custom-copilot.cmd",
                "claude_code_cli_path": "claude-cli"
            },
            "git": {
                "default_branch": "develop",
                "fallback_branch": "main",
            },
            "mcp_server": {
                "enabled": True,
                "restart_script": "scripts/restart.ps1",
                "name": "Test MCP",
            },
            "test_data": {
                "api_url": "https://example.com/api",
                "test_id": "TEST-001",
            },
            "work_artifacts_dir": "artifacts",
            "maintenance": {
                "agents": [
                    {
                        "name": "Custom Agent",
                        "prompt_file": "custom.md",
                        "frequency": 10,
                        "needs_worktree": True,
                        "merge_changes": False,
                        "model": "gpt-4o",
                        "enabled": True,
                    }
                ]
            },
            "model_sync": {
                "enabled": True,
                "interval_minutes": 30,
                "beta_only": False,
                "include_preview": False,
                "prune_unavailable": True,
                "create_beads_items": False,
                "issue_type": "feature",
                "priority": 1,
                "labels": ["model", "beta", "copilot", "preview"],
            },
        }

        config = ProjectConfig.from_dict(data)
        assert config.project_name == "MyProject"
        assert config.models.default == "gpt-4o"
        assert config.models.fallback == "gpt-4o-mini"
        assert config.ai_backend.provider == "claude-code"
        assert config.ai_backend.copilot_cli_path == "custom-copilot.cmd"
        assert config.ai_backend.claude_code_cli_path == "claude-cli"
        assert config.git.default_branch == "develop"
        assert config.git.fallback_branch == "main"
        assert config.mcp_server.enabled is True
        assert config.mcp_server.restart_script == "scripts/restart.ps1"
        assert config.mcp_server.name == "Test MCP"
        assert config.test_data["api_url"] == "https://example.com/api"
        assert config.work_artifacts_dir == "artifacts"
        assert config.model_sync.interval_minutes == 30
        assert config.model_sync.prune_unavailable is True
        assert config.model_sync.issue_type == "feature"
        assert len(config.maintenance.agents) == 1
        assert config.maintenance.agents[0].name == "Custom Agent"
        assert config.maintenance.agents[0].frequency == 10

    def test_from_dict_partial_maintenance(self):
        """When maintenance.agents is provided, it replaces defaults."""
        data = {
            "maintenance": {
                "agents": [
                    {"name": "Only Agent", "prompt_file": "only.md", "frequency": 1}
                ]
            }
        }
        config = ProjectConfig.from_dict(data)
        assert len(config.maintenance.agents) == 1
        assert config.maintenance.agents[0].name == "Only Agent"

    def test_from_dict_no_maintenance_keeps_defaults(self):
        """When maintenance section is absent, defaults are used."""
        config = ProjectConfig.from_dict({"project_name": "test"})
        assert len(config.maintenance.agents) == 7



class TestLoadConfigFile:
    """Tests for _load_config_file."""

    def test_load_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"project_name": "test"}))
        data = _load_config_file(config_file)
        assert data["project_name"] == "test"

    def test_load_json_invalid_root(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('"not a dict"')
        data = _load_config_file(config_file)
        assert data == {}

    def test_unsupported_extension(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        with pytest.raises(ValueError, match="Unsupported"):
            _load_config_file(config_file)

    def test_load_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("project_name: yaml_test\n")
        data = _load_config_file(config_file)
        assert data["project_name"] == "yaml_test"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_explicit_path_json(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "project_name": "ExplicitProject",
            "models": {"default": "gpt-4o"},
        }))
        config = load_config(config_path=config_file)
        assert config.project_name == "ExplicitProject"
        assert config.models.default == "gpt-4o"

    def test_caching(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"project_name": "Cached"}))
        config1 = load_config(config_path=config_file)
        # Second call without path should return cached
        config2 = load_config()
        assert config1 is config2

    def test_reset_clears_cache(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"project_name": "First"}))
        config1 = load_config(config_path=config_file)
        reset_config()
        config_file.write_text(json.dumps({"project_name": "Second"}))
        config2 = load_config(config_path=config_file)
        assert config2.project_name == "Second"
        assert config1 is not config2

    @patch("pokepoke.config._find_repo_root")
    def test_auto_discovery_json(self, mock_root, tmp_path):
        mock_root.return_value = tmp_path
        config_file = tmp_path / "pokepoke.config.json"
        config_file.write_text(json.dumps({"project_name": "AutoDiscovered"}))
        config = load_config()
        assert config.project_name == "AutoDiscovered"

    @patch("pokepoke.config._find_repo_root")
    def test_auto_discovery_pokepoke_dir(self, mock_root, tmp_path):
        mock_root.return_value = tmp_path
        pokepoke_dir = tmp_path / ".pokepoke"
        pokepoke_dir.mkdir()
        config_file = pokepoke_dir / "config.json"
        config_file.write_text(json.dumps({"project_name": "FromPokePoke"}))
        config = load_config()
        assert config.project_name == "FromPokePoke"

    @patch("pokepoke.config._find_repo_root")
    def test_no_config_returns_defaults(self, mock_root, tmp_path):
        mock_root.return_value = tmp_path
        config = load_config()
        assert config.project_name == ""
        assert config.models.default == "claude-opus-4.6"
        assert len(config.maintenance.agents) == 7

    @patch("pokepoke.config._find_repo_root")
    def test_pokepoke_yaml_takes_priority(self, mock_root, tmp_path):
        """Config in .pokepoke/config.yaml is preferred over pokepoke.config.json."""
        mock_root.return_value = tmp_path
        pokepoke_dir = tmp_path / ".pokepoke"
        pokepoke_dir.mkdir()

        # Create both files
        yaml_file = pokepoke_dir / "config.yaml"
        yaml_file.write_text("project_name: FromYAML\n")
        json_file = tmp_path / "pokepoke.config.json"
        json_file.write_text(json.dumps({"project_name": "FromJSON"}))

        config = load_config()
        # .pokepoke/config.yaml should be preferred
        assert config.project_name == "FromYAML"


class TestGetConfig:
    """Tests for get_config convenience function."""

    def test_returns_cached(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"project_name": "GetConfigTest"}))
        load_config(config_path=config_file)
        config = get_config()
        assert config.project_name == "GetConfigTest"


class TestMaintenanceAgentDefaults:
    """Tests for default maintenance agent behavior."""

    def test_all_defaults_enabled(self):
        config = MaintenanceConfig.defaults()
        for agent in config.agents:
            assert agent.enabled is True

    def test_janitor_merges(self):
        config = MaintenanceConfig.defaults()
        janitor = [a for a in config.agents if a.name == "Janitor"][0]
        assert janitor.merge_changes is True
        assert janitor.needs_worktree is True

    def test_beta_tester_discards(self):
        config = MaintenanceConfig.defaults()
        beta = [a for a in config.agents if a.name == "Beta Tester"][0]
        assert beta.merge_changes is False
        assert beta.needs_worktree is True

    def test_tech_debt_no_worktree(self):
        config = MaintenanceConfig.defaults()
        td = [a for a in config.agents if a.name == "Tech Debt"][0]
        assert td.needs_worktree is False

    def test_disabled_agent_from_dict(self):
        data = {
            "maintenance": {
                "agents": [
                    {
                        "name": "Disabled Agent",
                        "prompt_file": "test.md",
                        "frequency": 1,
                        "enabled": False,
                    }
                ]
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.maintenance.agents[0].enabled is False


class TestCommandTimeout:
    """Tests for command_timeout configuration."""

    def test_default_value(self):
        """Test that command_timeout has a default value of 300."""
        config = ProjectConfig()
        assert config.command_timeout == 300

    def test_from_dict_default(self):
        """Test that command_timeout defaults to 300 when not specified."""
        config = ProjectConfig.from_dict({})
        assert config.command_timeout == 300

    def test_from_dict_custom_value(self):
        """Test that command_timeout can be set via config dict."""
        data = {"command_timeout": 600}
        config = ProjectConfig.from_dict(data)
        assert config.command_timeout == 600

    def test_from_dict_minimum_enforcement(self):
        """Test that command_timeout enforces minimum of 30 seconds."""
        data = {"command_timeout": 10}  # Below minimum
        config = ProjectConfig.from_dict(data)
        assert config.command_timeout == 30  # Should be clamped to minimum

    def test_from_dict_zero_clamped(self):
        """Test that zero command_timeout is clamped to minimum."""
        data = {"command_timeout": 0}
        config = ProjectConfig.from_dict(data)
        assert config.command_timeout == 30


class TestAssignmentConfig:
    """Tests for AssignmentConfig and AssignmentRule parsing."""

    def test_defaults(self):
        """Default assignment config has no rules and weighted fallback."""
        config = ProjectConfig()
        assert config.assignment.rules == []
        assert config.assignment.fallback == "weighted"

    def test_from_dict_empty(self):
        """No assignment section yields defaults."""
        config = ProjectConfig.from_dict({})
        assert config.assignment.rules == []
        assert config.assignment.fallback == "weighted"

    def test_from_dict_with_rules(self):
        """Rules are correctly parsed from dict."""
        data = {
            "assignment": {
                "rules": [
                    {
                        "match": {"issue_type": "bug"},
                        "model": "claude-sonnet-4.5",
                    },
                    {
                        "match": {"issue_type": "feature", "priority_max": 1, "labels": ["critical"]},
                        "model": "claude-opus-4.6",
                        "prompt_template": "high-pri-feature",
                    },
                ],
                "fallback": "gpt-5",
            }
        }
        config = ProjectConfig.from_dict(data)
        assert len(config.assignment.rules) == 2
        assert config.assignment.fallback == "gpt-5"

        r0 = config.assignment.rules[0]
        assert r0.match.issue_type == "bug"
        assert r0.match.labels is None
        assert r0.match.priority_max is None
        assert r0.model == "claude-sonnet-4.5"
        assert r0.prompt_template is None

        r1 = config.assignment.rules[1]
        assert r1.match.issue_type == "feature"
        assert r1.match.priority_max == 1
        assert r1.match.labels == ["critical"]
        assert r1.model == "claude-opus-4.6"
        assert r1.prompt_template == "high-pri-feature"

    def test_from_dict_empty_rules_list(self):
        """Empty rules list is valid."""
        data = {"assignment": {"rules": []}}
        config = ProjectConfig.from_dict(data)
        assert config.assignment.rules == []
        assert config.assignment.fallback == "weighted"

    def test_rule_with_no_match_section(self):
        """A rule with no match section gets empty match criteria."""
        data = {"assignment": {"rules": [{"model": "some-model"}]}}
        config = ProjectConfig.from_dict(data)
        assert len(config.assignment.rules) == 1
        rule = config.assignment.rules[0]
        assert rule.match.issue_type is None
        assert rule.match.labels is None
        assert rule.match.priority_max is None
        assert rule.model == "some-model"


class TestUnknownKeyDetection:
    """Tests for detecting unknown/typo'd config keys."""

    def test_typo_in_top_level_key_raises(self):
        """A typo like 'comand_timeout' should raise an error."""
        data = {"comand_timeout": 600}  # Typo: missing 'm' in command
        with pytest.raises(ValueError, match="Unknown configuration key"):
            ProjectConfig.from_dict(data)

    def test_typo_in_nested_key_raises(self):
        """A typo in nested config should raise an error."""
        data = {"models": {"defualt": "gpt-4o"}}  # Typo: 'defualt' instead of 'default'
        with pytest.raises(ValueError, match="Unknown configuration key"):
            ProjectConfig.from_dict(data)

    def test_unknown_section_raises(self):
        """A completely unknown top-level section should raise an error."""
        data = {"unknown_section": {"key": "value"}}
        with pytest.raises(ValueError, match="Unknown configuration key"):
            ProjectConfig.from_dict(data)

    def test_valid_config_does_not_raise(self):
        """Valid config keys should not raise errors."""
        data = {
            "project_name": "test",
            "command_timeout": 600,
            "models": {"default": "gpt-4o"},
        }
        config = ProjectConfig.from_dict(data)
        assert config.project_name == "test"
        assert config.command_timeout == 600
        assert config.models.default == "gpt-4o"


class TestGateAgentEnabled:
    """Tests for gate_agent_enabled configuration."""

    def test_default_value(self):
        config = ProjectConfig()
        assert config.gate_agent_enabled is True

    def test_from_dict_default(self):
        config = ProjectConfig.from_dict({})
        assert config.gate_agent_enabled is True

    def test_from_dict_disabled(self):
        config = ProjectConfig.from_dict({"gate_agent_enabled": False})
        assert config.gate_agent_enabled is False

    def test_from_dict_enabled_explicit(self):
        config = ProjectConfig.from_dict({"gate_agent_enabled": True})
        assert config.gate_agent_enabled is True
