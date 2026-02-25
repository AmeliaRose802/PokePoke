"""Project configuration system for PokePoke.

Loads project-specific settings from .pokepoke/config.yaml, allowing PokePoke
to be used generically on any project without hardcoded values.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pokepoke.model_sync_config import ModelSyncConfig, parse_model_sync_config

try:
    import yaml  # type: ignore[import-untyped]
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

import json
# Default model identifiers (single source of truth)
DEFAULT_MODEL = "claude-opus-4.6"
FALLBACK_MODEL = "claude-sonnet-4.5"


@dataclass
class ModelConfig:
    """LLM model configuration."""
    default: str = DEFAULT_MODEL
    fallback: str = FALLBACK_MODEL
    candidate_models: list[str] = field(default_factory=list)
@dataclass
class AIBackendConfig:
    """AI backend configuration."""
    provider: str = "copilot"
    copilot_cli_path: str = "copilot.cmd"
    claude_code_cli_path: str = "claude"
@dataclass
class MaintenanceAgentConfig:
    """Configuration for a single maintenance agent."""
    name: str = ""
    prompt_file: str = ""
    frequency: int = 5
    needs_worktree: bool = False
    merge_changes: bool = True
    model: str | None = None
    enabled: bool = True
    conflicts_with: list[str] = field(default_factory=list)
@dataclass
class MaintenanceConfig:
    """Maintenance agent scheduling configuration."""
    agents: list[MaintenanceAgentConfig] = field(default_factory=list)

    @staticmethod
    def defaults() -> 'MaintenanceConfig':
        """Return the default maintenance configuration."""
        return MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Tech Debt",
                prompt_file="tech-debt.md",
                frequency=5,
                needs_worktree=False,
            ),
            MaintenanceAgentConfig(
                name="Janitor",
                prompt_file="janitor.md",
                frequency=2,
                needs_worktree=True,
                merge_changes=True,
            ),
            MaintenanceAgentConfig(
                name="Backlog Cleanup",
                prompt_file="backlog-cleanup.md",
                frequency=7,
                needs_worktree=True,
                merge_changes=False,
            ),
            MaintenanceAgentConfig(
                name="Beta Tester",
                prompt_file="beta-tester.md",
                frequency=3,
                needs_worktree=True,
                merge_changes=False,
            ),
            MaintenanceAgentConfig(
                name="Code Review",
                prompt_file="code-reviewer.md",
                frequency=5,
                needs_worktree=False,
                model="gpt-5.1-codex",
            ),
            MaintenanceAgentConfig(
                name="Worktree Cleanup",
                prompt_file="worktree-cleanup.md",
                frequency=4,
                needs_worktree=False,
            ),
            MaintenanceAgentConfig(
                name="Model Sync",
                prompt_file="",
                frequency=1,
                needs_worktree=False,
                merge_changes=False,
            ),
        ])
@dataclass
class MpcServerConfig:
    """MCP server configuration."""
    enabled: bool = False
    restart_script: str | None = None
    name: str | None = None
@dataclass
class GitConfig:
    """Git-related configuration."""
    default_branch: str | None = None
    fallback_branch: str = "master"

    def get_preferred_branch(self) -> str:
        """Get the preferred branch, falling back to fallback_branch if not set."""
        if self.default_branch:
            return self.default_branch
        return self.fallback_branch
@dataclass
class PreflightHealthConfig:
    """Pre-flight health check configuration."""
    enabled: bool = True
    min_disk_space_gb: float = 1.0
    lock_timeout_seconds: float = 30.0
    worktree_test_timeout: float = 60.0
    max_orphan_worktrees: int = 10
    git_operation_timeout: float = 30.0
    enable_self_repair: bool = True
    max_repair_attempts: int = 3
    fail_on_environmental_errors: bool = True
    fail_on_critical_errors: bool = True
    graceful_shutdown_on_failure: bool = True


@dataclass
class AssignmentRuleMatch:
    """Criteria for matching a work item to an assignment rule."""
    issue_type: str | None = None
    labels: list[str] | None = None
    priority_max: int | None = None  # Match items with priority <= this value
@dataclass
class AssignmentRule:
    """A single assignment rule mapping matched work items to models/prompts."""
    match: AssignmentRuleMatch = field(default_factory=AssignmentRuleMatch)
    model: str | None = None
    prompt_template: str | None = None
@dataclass
class AssignmentConfig:
    """Per-work-item assignment settings.

    Rules are evaluated in order; the first matching rule wins.
    ``fallback`` controls behaviour when no rule matches:
      - ``"weighted"`` (default): use performance-weighted A/B selection
      - any other string: treat as a literal model name
    """
    rules: list[AssignmentRule] = field(default_factory=list)
    fallback: str = "weighted"
@dataclass
class ActivityWatchdogConfig:
    """Configuration for the activity watchdog that detects hung Copilot sessions."""
    enabled: bool = True
    timeout_seconds: int = 600  # 10 minutes
    check_interval_seconds: int = 30
@dataclass
class ProjectConfig:
    """Top-level project configuration."""
    project_name: str = ""
    models: ModelConfig = field(default_factory=ModelConfig)
    ai_backend: AIBackendConfig = field(default_factory=AIBackendConfig)
    maintenance: MaintenanceConfig = field(default_factory=MaintenanceConfig.defaults)
    model_sync: ModelSyncConfig = field(default_factory=ModelSyncConfig)
    mcp_server: MpcServerConfig = field(default_factory=MpcServerConfig)
    git: GitConfig = field(default_factory=GitConfig)
    preflight_health: PreflightHealthConfig = field(default_factory=PreflightHealthConfig)
    test_data: dict[str, str] = field(default_factory=dict)
    work_artifacts_dir: str | None = None
    max_parallel_agents: int = 1
    command_timeout: int = 300  # Default 5 minutes for long-running commands
    gate_agent_enabled: bool = True
    activity_watchdog: ActivityWatchdogConfig = field(default_factory=ActivityWatchdogConfig)
    assignment: AssignmentConfig = field(default_factory=AssignmentConfig)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> 'ProjectConfig':
        """Create a ProjectConfig from a dictionary (parsed YAML/JSON)."""
        config = ProjectConfig()

        config.project_name = data.get("project_name", "")

        # Models
        models_data = data.get("models", {})
        config.models = ModelConfig(
            default=models_data.get("default", DEFAULT_MODEL),
            fallback=models_data.get("fallback", FALLBACK_MODEL),
            candidate_models=models_data.get("candidate_models", []),
        )

        # AI backend
        backend_data = data.get("ai_backend", {})
        config.ai_backend = AIBackendConfig(
            provider=backend_data.get("provider", "copilot"),
            copilot_cli_path=backend_data.get("copilot_cli_path", "copilot.cmd"),
            claude_code_cli_path=backend_data.get("claude_code_cli_path", "claude"),
        )

        # Git
        git_data = data.get("git", {})
        config.git = GitConfig(
            default_branch=git_data.get("default_branch"),
            fallback_branch=git_data.get("fallback_branch", "master"),
        )

        # MCP Server
        mcp_data = data.get("mcp_server", {})
        config.mcp_server = MpcServerConfig(
            enabled=mcp_data.get("enabled", False),
            restart_script=mcp_data.get("restart_script"),
            name=mcp_data.get("name"),
        )

        # Test data
        config.test_data = data.get("test_data", {})

        # Work artifacts directory
        config.work_artifacts_dir = data.get("work_artifacts_dir")

        # Max parallel agents
        config.max_parallel_agents = max(1, int(data.get("max_parallel_agents", 1)))

        # Command timeout (default 300 seconds)
        config.command_timeout = max(30, int(data.get("command_timeout", 300)))

        # Gate agent
        gate_val = data.get("gate_agent_enabled")
        if gate_val is not None:
            config.gate_agent_enabled = bool(gate_val)

        # Activity watchdog
        watchdog_data = data.get("activity_watchdog", {})
        config.activity_watchdog = ActivityWatchdogConfig(
            enabled=watchdog_data.get("enabled", True),
            timeout_seconds=max(60, int(watchdog_data.get("timeout_seconds", 600))),
            check_interval_seconds=max(10, int(watchdog_data.get("check_interval_seconds", 30))),
        )

        # Preflight health checks
        health_data = data.get("preflight_health", {})
        config.preflight_health = PreflightHealthConfig(
            enabled=health_data.get("enabled", True),
            min_disk_space_gb=max(0.1, float(health_data.get("min_disk_space_gb", 1.0))),
            lock_timeout_seconds=max(5.0, float(health_data.get("lock_timeout_seconds", 30.0))),
            worktree_test_timeout=max(10.0, float(health_data.get("worktree_test_timeout", 60.0))),
            max_orphan_worktrees=max(0, int(health_data.get("max_orphan_worktrees", 10))),
            git_operation_timeout=max(5.0, float(health_data.get("git_operation_timeout", 30.0))),
            enable_self_repair=health_data.get("enable_self_repair", True),
            max_repair_attempts=max(1, int(health_data.get("max_repair_attempts", 3))),
            fail_on_environmental_errors=health_data.get("fail_on_environmental_errors", True),
            fail_on_critical_errors=health_data.get("fail_on_critical_errors", True),
            graceful_shutdown_on_failure=health_data.get("graceful_shutdown_on_failure", True),
        )

        # Maintenance agents
        maint_data = data.get("maintenance", {})
        agents_data = maint_data.get("agents")
        if agents_data is not None:
            config.maintenance = MaintenanceConfig(agents=[
                MaintenanceAgentConfig(
                    name=a.get("name", ""),
                    prompt_file=a.get("prompt_file", ""),
                    frequency=a.get("frequency", 5),
                    needs_worktree=a.get("needs_worktree", False),
                    merge_changes=a.get("merge_changes", True),
                    model=a.get("model"),
                    enabled=a.get("enabled", True),
                    conflicts_with=a.get("conflicts_with", []),
                )
                for a in agents_data
            ])
        # else: keep defaults from field(default_factory=...)

        # Model sync
        config.model_sync = parse_model_sync_config(data.get("model_sync", {}))

        # Assignment rules
        assign_data = data.get("assignment", {})
        rules_data = assign_data.get("rules", [])
        config.assignment = AssignmentConfig(
            rules=[
                AssignmentRule(
                    match=AssignmentRuleMatch(
                        issue_type=r.get("match", {}).get("issue_type"),
                        labels=r.get("match", {}).get("labels"),
                        priority_max=r.get("match", {}).get("priority_max"),
                    ),
                    model=r.get("model"),
                    prompt_template=r.get("prompt_template"),
                )
                for r in rules_data
            ],
            fallback=assign_data.get("fallback", "weighted"),
        )

        return config




def _find_repo_root() -> Path:
    """Find the repository root of the target project.

    Walks up from the current working directory (not from PokePoke's own
    source tree) so that config is loaded from the project PokePoke is
    being run *on*, not from PokePoke's own repository.
    """
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return Path.cwd()


def _load_config_file(config_path: Path) -> dict[str, Any]:
    """Load a config file (YAML or JSON).

    Args:
        config_path: Path to the config file.

    Returns:
        Parsed configuration dictionary.
    """
    content = config_path.read_text(encoding="utf-8")

    if config_path.suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required to load .yaml config files. "
                "Install it with: pip install pyyaml"
            )
        data = yaml.safe_load(content)
        return data if isinstance(data, dict) else {}

    if config_path.suffix == ".json":
        data = json.loads(content)
        return data if isinstance(data, dict) else {}

    raise ValueError(f"Unsupported config file format: {config_path.suffix}")


# Module-level cached config
_cached_config: ProjectConfig | None = None


def load_config(config_path: Path | None = None) -> ProjectConfig:
    """Load the project configuration.

    Searches for config in this order:
    1. Explicit path (if provided)
    2. .pokepoke/config.yaml
    3. .pokepoke/config.yml
    4. .pokepoke/config.json
    5. pokepoke.config.json (repo root)

    If no config file is found, returns defaults.

    Args:
        config_path: Optional explicit path to config file.

    Returns:
        Loaded ProjectConfig.
    """
    global _cached_config

    if _cached_config is not None and config_path is None:
        return _cached_config

    repo_root = _find_repo_root()

    if config_path is not None:
        data = _load_config_file(config_path)
        config = ProjectConfig.from_dict(data)
        _cached_config = config
        return config

    # Search for config files in order of preference
    candidates = [
        repo_root / ".pokepoke" / "config.yaml",
        repo_root / ".pokepoke" / "config.yml",
        repo_root / ".pokepoke" / "config.json",
        repo_root / "pokepoke.config.json",
    ]

    for candidate in candidates:
        if candidate.exists():
            data = _load_config_file(candidate)
            config = ProjectConfig.from_dict(data)
            _cached_config = config
            return config

    # No config file found - use defaults
    config = ProjectConfig()
    _cached_config = config
    return config


def reset_config() -> None:
    """Reset the cached configuration (useful for testing)."""
    global _cached_config
    _cached_config = None


def get_config() -> ProjectConfig:
    """Get the current project configuration (cached).

    Returns:
        Current ProjectConfig instance.
    """
    return load_config()
