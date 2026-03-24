"""Project configuration system for PokePoke.

Loads project-specific settings from .pokepoke/config.yaml, allowing PokePoke
to be used generically on any project without hardcoded values.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import dacite

from pokepoke.models.model_sync_config import ModelSyncConfig, parse_model_sync_config

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

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.min_disk_space_gb = max(0.1, self.min_disk_space_gb)
        self.lock_timeout_seconds = max(5.0, self.lock_timeout_seconds)
        self.worktree_test_timeout = max(10.0, self.worktree_test_timeout)
        self.max_orphan_worktrees = max(0, self.max_orphan_worktrees)
        self.git_operation_timeout = max(5.0, self.git_operation_timeout)
        self.max_repair_attempts = max(1, self.max_repair_attempts)


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
class QualityGateOverrides:
    """Repo-specific overrides for quality gate checks (None = inherit global)."""
    coverage_threshold: float | None = None
    max_file_length: int | None = None
    allow_skipped_tests: bool | None = None
    extra_checks: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.coverage_threshold is not None:
            self.coverage_threshold = max(0.0, min(100.0, self.coverage_threshold))
        if self.max_file_length is not None:
            self.max_file_length = max(1, self.max_file_length)


@dataclass
class RepoConfig:
    """Configuration for an individual repository in multi-repo mode."""
    path: str = ""
    priority_weight: int = 1
    enabled: bool = True
    max_workers: int = 0  # Per-repo worker cap (0 = no per-repo limit, uses global pool share)
    beads_db_path: str | None = None  # Explicit beads DB path; auto-discovered when None
    copilot_instructions_path: str | None = None  # Custom copilot instructions file
    quality_gate_overrides: QualityGateOverrides | None = None

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.priority_weight = max(1, self.priority_weight)
        self.max_workers = max(0, self.max_workers)


@dataclass
class PerformanceThresholdsConfig:
    """Configurable thresholds for the PerformanceMonitor."""
    enabled: bool = True
    max_merge_queue_depth: int = 5
    max_lock_wait_seconds: float = 30.0
    max_iteration_seconds: float = 30.0
    min_memory_mb: float = 256.0
    min_success_rate: float = 0.5

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.max_merge_queue_depth = max(1, self.max_merge_queue_depth)
        self.max_lock_wait_seconds = max(1.0, self.max_lock_wait_seconds)
        self.max_iteration_seconds = max(1.0, self.max_iteration_seconds)
        self.min_memory_mb = max(32.0, self.min_memory_mb)
        self.min_success_rate = max(0.0, min(1.0, self.min_success_rate))


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
    max_copilot_failure_retries: int = 2  # Max retries when Copilot session fails (0 = no retry)
    idle_timeout_seconds: int = 90  # Seconds to wait before confirming a session is idle
    session_inactivity_timeout: int = 900  # Seconds with no SDK events before treating session as dead
    tool_call_timeout: int = 900  # Max seconds for a single tool invocation before killing it
    process_output_timeout: int = 300  # Seconds with no output before treating process as unresponsive
    max_ping_failures: int = 3  # Consecutive ping failures before declaring process dead
    assignment: AssignmentConfig = field(default_factory=AssignmentConfig)
    performance_thresholds: PerformanceThresholdsConfig = field(
        default_factory=PerformanceThresholdsConfig,
    )
    repos: list[RepoConfig] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.max_parallel_agents = max(1, self.max_parallel_agents)
        self.command_timeout = max(30, self.command_timeout)
        self.max_copilot_failure_retries = max(0, self.max_copilot_failure_retries)
        self.idle_timeout_seconds = max(10, self.idle_timeout_seconds)
        self.session_inactivity_timeout = max(60, self.session_inactivity_timeout)
        self.tool_call_timeout = max(60, self.tool_call_timeout)
        self.process_output_timeout = max(30, self.process_output_timeout)
        self.max_ping_failures = max(1, self.max_ping_failures)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> 'ProjectConfig':
        """Create a ProjectConfig from a dictionary (parsed YAML/JSON).

        Uses dacite for deserialization with strict mode to catch unknown keys.
        """
        # Handle special cases that need preprocessing
        processed_data = dict(data)

        # Handle model_sync specially since it has custom parsing logic
        if "model_sync" in processed_data:
            processed_data["model_sync"] = parse_model_sync_config(
                processed_data["model_sync"]
            )

        # Handle maintenance default behavior: if no agents key, use defaults
        if "maintenance" in processed_data:
            maint_data = processed_data["maintenance"]
            if "agents" not in maint_data:
                # No agents specified, keep default factory behavior
                del processed_data["maintenance"]

        # Migrate removed activity_watchdog config: extract idle_timeout_seconds
        # if present, then drop the key so strict parsing doesn't fail.
        if "activity_watchdog" in processed_data:
            aw = processed_data.pop("activity_watchdog")
            if isinstance(aw, dict) and "idle_timeout_seconds" in aw:
                processed_data.setdefault("idle_timeout_seconds", aw["idle_timeout_seconds"])

        dacite_config = dacite.Config(
            strict=True,  # Raise on unknown keys
            cast=[bool, int, float],  # Allow type coercion for these types
        )

        try:
            return dacite.from_dict(
                data_class=ProjectConfig,
                data=processed_data,
                config=dacite_config,
            )
        except dacite.UnexpectedDataError as e:
            # Provide helpful error message for typos like "comand_timeout"
            raise ValueError(
                f"Unknown configuration key(s): {e}. "
                "Check for typos in your config file."
            ) from e


def _find_repo_root() -> Path:
    """Find the repository root by walking up from cwd."""
    current = Path.cwd().resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return Path.cwd()


def _load_config_file(config_path: Path) -> dict[str, Any]:
    """Load a config file (YAML or JSON) and return parsed dict."""
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
    """Load project configuration from explicit path or auto-discovered file.

    Search order: .pokepoke/config.yaml, .yml, .json, then pokepoke.config.json.
    Returns defaults if no config file is found.
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
