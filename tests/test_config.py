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
    QualityGateOverrides,
    RepoConfig,
    load_config,
    reset_config,
    get_config,
    _find_repo_root,  # noqa: F401  # used via patch strings
    _load_config_file,
)
from pokepoke.repo_config_loader import (
    parse_repos_cli,
    validate_repo_config,
    validate_repo_configs,
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


class TestToolCallTimeout:
    """Tests for tool_call_timeout configuration."""

    def test_default_value(self):
        """Test that tool_call_timeout defaults to 600."""
        config = ProjectConfig()
        assert config.tool_call_timeout == 600

    def test_from_dict_default(self):
        """Test that tool_call_timeout defaults to 600 when not specified."""
        config = ProjectConfig.from_dict({})
        assert config.tool_call_timeout == 600

    def test_from_dict_custom_value(self):
        """Test that tool_call_timeout can be set via config dict."""
        data = {"tool_call_timeout": 900}
        config = ProjectConfig.from_dict(data)
        assert config.tool_call_timeout == 900

    def test_from_dict_minimum_enforcement(self):
        """Test that tool_call_timeout enforces minimum of 60 seconds."""
        data = {"tool_call_timeout": 10}
        config = ProjectConfig.from_dict(data)
        assert config.tool_call_timeout == 60

    def test_from_dict_zero_clamped(self):
        """Test that zero tool_call_timeout is clamped to minimum."""
        data = {"tool_call_timeout": 0}
        config = ProjectConfig.from_dict(data)
        assert config.tool_call_timeout == 60


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


class TestMaxCopilotFailureRetries:
    """Tests for max_copilot_failure_retries configuration."""

    def test_default_value(self):
        """Default retries is 2."""
        config = ProjectConfig()
        assert config.max_copilot_failure_retries == 2

    def test_from_dict_default(self):
        """Defaults to 2 when not specified."""
        config = ProjectConfig.from_dict({})
        assert config.max_copilot_failure_retries == 2

    def test_from_dict_custom_value(self):
        """Can be set to any non-negative integer."""
        config = ProjectConfig.from_dict({"max_copilot_failure_retries": 5})
        assert config.max_copilot_failure_retries == 5

    def test_from_dict_zero_disables_retry(self):
        """Setting to 0 disables retries."""
        config = ProjectConfig.from_dict({"max_copilot_failure_retries": 0})
        assert config.max_copilot_failure_retries == 0

    def test_negative_clamped_to_zero(self):
        """Negative values are clamped to 0 (no retry) by __post_init__."""
        config = ProjectConfig.from_dict({"max_copilot_failure_retries": -3})
        assert config.max_copilot_failure_retries == 0


class TestQualityGateOverrides:
    """Tests for QualityGateOverrides dataclass."""

    def test_defaults(self):
        qg = QualityGateOverrides()
        assert qg.coverage_threshold is None
        assert qg.max_file_length is None
        assert qg.allow_skipped_tests is None
        assert qg.extra_checks == []

    def test_custom_values(self):
        qg = QualityGateOverrides(
            coverage_threshold=90.0,
            max_file_length=500,
            allow_skipped_tests=True,
            extra_checks=["mypy", "ruff"],
        )
        assert qg.coverage_threshold == 90.0
        assert qg.max_file_length == 500
        assert qg.allow_skipped_tests is True
        assert qg.extra_checks == ["mypy", "ruff"]

    def test_coverage_threshold_clamped_high(self):
        qg = QualityGateOverrides(coverage_threshold=150.0)
        assert qg.coverage_threshold == 100.0

    def test_coverage_threshold_clamped_low(self):
        qg = QualityGateOverrides(coverage_threshold=-10.0)
        assert qg.coverage_threshold == 0.0

    def test_max_file_length_clamped(self):
        qg = QualityGateOverrides(max_file_length=0)
        assert qg.max_file_length == 1

    def test_none_values_not_clamped(self):
        """None values should remain None (inherit global defaults)."""
        qg = QualityGateOverrides()
        assert qg.coverage_threshold is None
        assert qg.max_file_length is None


class TestRepoConfigExtended:
    """Tests for extended RepoConfig fields."""

    def test_new_field_defaults(self):
        rc = RepoConfig()
        assert rc.beads_db_path is None
        assert rc.copilot_instructions_path is None
        assert rc.quality_gate_overrides is None

    def test_all_fields_set(self):
        qg = QualityGateOverrides(coverage_threshold=85.0)
        rc = RepoConfig(
            path="/my/repo",
            priority_weight=5,
            max_workers=2,
            beads_db_path="/my/repo/.beads",
            copilot_instructions_path="instructions.md",
            quality_gate_overrides=qg,
        )
        assert rc.path == "/my/repo"
        assert rc.beads_db_path == "/my/repo/.beads"
        assert rc.copilot_instructions_path == "instructions.md"
        assert rc.quality_gate_overrides is not None
        assert rc.quality_gate_overrides.coverage_threshold == 85.0

    def test_from_dict_with_repos(self):
        """RepoConfig with new fields round-trips through from_dict."""
        data = {
            "repos": [
                {
                    "path": "/repo/alpha",
                    "priority_weight": 3,
                    "max_workers": 2,
                    "beads_db_path": "/repo/alpha/.beads",
                    "copilot_instructions_path": "custom.md",
                    "quality_gate_overrides": {
                        "coverage_threshold": 90.0,
                        "max_file_length": 400,
                        "allow_skipped_tests": False,
                        "extra_checks": ["ruff"],
                    },
                },
                {
                    "path": "/repo/beta",
                    "enabled": False,
                },
            ]
        }
        config = ProjectConfig.from_dict(data)
        assert len(config.repos) == 2

        r0 = config.repos[0]
        assert r0.path == "/repo/alpha"
        assert r0.priority_weight == 3
        assert r0.max_workers == 2
        assert r0.beads_db_path == "/repo/alpha/.beads"
        assert r0.copilot_instructions_path == "custom.md"
        assert r0.quality_gate_overrides is not None
        assert r0.quality_gate_overrides.coverage_threshold == 90.0
        assert r0.quality_gate_overrides.max_file_length == 400
        assert r0.quality_gate_overrides.allow_skipped_tests is False
        assert r0.quality_gate_overrides.extra_checks == ["ruff"]

        r1 = config.repos[1]
        assert r1.path == "/repo/beta"
        assert r1.enabled is False
        assert r1.quality_gate_overrides is None

    def test_from_dict_repos_no_quality_overrides(self):
        """Repos without quality_gate_overrides get None."""
        data = {"repos": [{"path": "/r"}]}
        config = ProjectConfig.from_dict(data)
        assert config.repos[0].quality_gate_overrides is None


class TestValidateRepoConfig:
    """Tests for validate_repo_config function."""

    def test_empty_path_is_invalid(self):
        result = validate_repo_config(RepoConfig(path=""))
        assert not result.valid
        assert any("empty" in e.lower() for e in result.errors)

    def test_nonexistent_path_is_invalid(self, tmp_path):
        bad = tmp_path / "nonexistent"
        result = validate_repo_config(RepoConfig(path=str(bad)))
        assert not result.valid
        assert any("does not exist" in e for e in result.errors)

    def test_valid_repo_with_beads(self, tmp_path):
        """Repo with .beads dir should be valid with no warnings."""
        (tmp_path / ".beads").mkdir()
        result = validate_repo_config(RepoConfig(path=str(tmp_path)))
        assert result.valid
        assert result.errors == []
        assert result.warnings == []

    def test_valid_repo_without_beads_warns(self, tmp_path):
        """Repo without .beads should warn but still be valid."""
        result = validate_repo_config(RepoConfig(path=str(tmp_path)))
        assert result.valid
        assert any("beads" in w.lower() or ".beads" in w for w in result.warnings)

    def test_explicit_beads_db_path_valid(self, tmp_path):
        beads_dir = tmp_path / "custom_beads"
        beads_dir.mkdir()
        result = validate_repo_config(RepoConfig(
            path=str(tmp_path),
            beads_db_path=str(beads_dir),
        ))
        assert result.valid
        assert result.warnings == []

    def test_explicit_beads_db_path_invalid(self, tmp_path):
        result = validate_repo_config(RepoConfig(
            path=str(tmp_path),
            beads_db_path=str(tmp_path / "doesnt_exist"),
        ))
        assert result.valid  # Still valid as a path, but warns
        assert any("beads_db_path" in w for w in result.warnings)

    def test_copilot_instructions_exists(self, tmp_path):
        instr = tmp_path / "instructions.md"
        instr.write_text("# Instructions")
        result = validate_repo_config(RepoConfig(
            path=str(tmp_path),
            copilot_instructions_path=str(instr),
        ))
        # No warning about copilot instructions path not existing
        assert not any("copilot instructions path does not exist" in w.lower() for w in result.warnings)

    def test_copilot_instructions_missing_warns(self, tmp_path):
        (tmp_path / ".beads").mkdir()
        result = validate_repo_config(RepoConfig(
            path=str(tmp_path),
            copilot_instructions_path="nonexistent.md",
        ))
        assert result.valid
        assert any("instructions" in w.lower() for w in result.warnings)

    def test_copilot_instructions_relative_path(self, tmp_path):
        """Relative path should resolve against repo path."""
        (tmp_path / ".beads").mkdir()
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "copilot.md").write_text("# Help")
        result = validate_repo_config(RepoConfig(
            path=str(tmp_path),
            copilot_instructions_path="docs/copilot.md",
        ))
        assert not any("instructions" in w.lower() for w in result.warnings)

    def test_quality_gate_zero_coverage_warns(self, tmp_path):
        (tmp_path / ".beads").mkdir()
        qg = QualityGateOverrides(coverage_threshold=0.0)
        result = validate_repo_config(RepoConfig(
            path=str(tmp_path),
            quality_gate_overrides=qg,
        ))
        assert any("coverage_threshold" in w for w in result.warnings)


class TestValidateRepoConfigs:
    """Tests for validate_repo_configs (batch validation)."""

    def test_empty_list(self):
        assert validate_repo_configs([]) == []

    def test_disabled_repo_skipped(self):
        results = validate_repo_configs([RepoConfig(path="", enabled=False)])
        assert len(results) == 1
        assert results[0].valid is True

    def test_mixed_valid_invalid(self, tmp_path):
        (tmp_path / ".beads").mkdir()
        repos = [
            RepoConfig(path=str(tmp_path)),
            RepoConfig(path=str(tmp_path / "bad")),
        ]
        results = validate_repo_configs(repos)
        assert results[0].valid is True
        assert results[1].valid is False


class TestParseReposCli:
    """Tests for parse_repos_cli function."""

    def test_plain_path(self):
        configs = parse_repos_cli(["/repo/alpha"])
        assert len(configs) == 1
        assert configs[0].path == "/repo/alpha"
        assert configs[0].priority_weight == 1
        assert configs[0].max_workers == 0
        assert configs[0].enabled is True

    def test_path_with_weight(self):
        configs = parse_repos_cli(["/repo/alpha:weight=5"])
        assert configs[0].priority_weight == 5

    def test_path_with_multiple_options(self):
        configs = parse_repos_cli(["/repo/alpha:weight=3:max_workers=2"])
        assert configs[0].priority_weight == 3
        assert configs[0].max_workers == 2

    def test_disabled_option(self):
        configs = parse_repos_cli(["/repo/x:disabled=true"])
        assert configs[0].enabled is False

    def test_multiple_repos(self):
        configs = parse_repos_cli(["/repo/a", "/repo/b:weight=10"])
        assert len(configs) == 2
        assert configs[0].path == "/repo/a"
        assert configs[0].priority_weight == 1
        assert configs[1].path == "/repo/b"
        assert configs[1].priority_weight == 10

    def test_empty_list(self):
        assert parse_repos_cli([]) == []

    def test_disabled_yes_variant(self):
        configs = parse_repos_cli(["/repo/x:disabled=yes"])
        assert configs[0].enabled is False

    def test_disabled_1_variant(self):
        configs = parse_repos_cli(["/repo/x:disabled=1"])
        assert configs[0].enabled is False

    def test_disabled_false_stays_enabled(self):
        configs = parse_repos_cli(["/repo/x:disabled=false"])
        assert configs[0].enabled is True

    def test_windows_drive_letter_plain_path(self):
        configs = parse_repos_cli([r"C:\src\repo"])
        assert len(configs) == 1
        assert configs[0].path == r"C:\src\repo"
        assert configs[0].priority_weight == 1

    def test_windows_drive_letter_with_weight(self):
        configs = parse_repos_cli([r"C:\src\repo:weight=5"])
        assert configs[0].path == r"C:\src\repo"
        assert configs[0].priority_weight == 5

    def test_windows_drive_letter_with_multiple_options(self):
        configs = parse_repos_cli([r"C:\src\repo:weight=3:max_workers=2"])
        assert configs[0].path == r"C:\src\repo"
        assert configs[0].priority_weight == 3
        assert configs[0].max_workers == 2

    def test_windows_drive_letter_disabled(self):
        configs = parse_repos_cli([r"D:\projects\myrepo:disabled=true"])
        assert configs[0].path == r"D:\projects\myrepo"
        assert configs[0].enabled is False

    def test_windows_forward_slash_drive_path(self):
        configs = parse_repos_cli(["C:/src/repo:weight=7"])
        assert configs[0].path == "C:/src/repo"
        assert configs[0].priority_weight == 7

    def test_mixed_windows_and_unix_repos(self):
        configs = parse_repos_cli([r"C:\repo\a:weight=2", "/repo/b:weight=3"])
        assert len(configs) == 2
        assert configs[0].path == r"C:\repo\a"
        assert configs[0].priority_weight == 2
        assert configs[1].path == "/repo/b"
        assert configs[1].priority_weight == 3
