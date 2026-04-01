"""Project configuration system for PokePoke."""
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import dacite

from pokepoke.models.model_sync_config import ModelSyncConfig, parse_model_sync_config

logger = logging.getLogger(__name__)

try:
    import yaml  # type: ignore[import-untyped]
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

import json

import pokepoke.constants as _c

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
    custom: bool = False  # True if this is a user-created custom agent
    description: str = ""  # Optional description of the agent's purpose
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
class MCPServerConfig:
    """MCP server configuration."""
    enabled: bool = False
    restart_script: str | None = None
    name: str | None = None


# Backwards-compatible alias (old typo kept to avoid breaking imports).
MpcServerConfig = MCPServerConfig
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
    min_disk_space_gb: float = _c.DEFAULT_MIN_DISK_SPACE_GB
    lock_timeout_seconds: float = _c.DEFAULT_LOCK_TIMEOUT_SECONDS
    worktree_test_timeout: float = _c.DEFAULT_WORKTREE_TEST_TIMEOUT
    max_orphan_worktrees: int = _c.DEFAULT_MAX_ORPHAN_WORKTREES
    git_operation_timeout: float = _c.DEFAULT_GIT_OPERATION_TIMEOUT
    enable_self_repair: bool = True
    max_repair_attempts: int = _c.DEFAULT_MAX_REPAIR_ATTEMPTS
    fail_on_environmental_errors: bool = True
    fail_on_critical_errors: bool = True
    graceful_shutdown_on_failure: bool = True

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.min_disk_space_gb = max(_c.MIN_DISK_SPACE_GB, self.min_disk_space_gb)
        self.lock_timeout_seconds = max(_c.MIN_LOCK_TIMEOUT_SECONDS, self.lock_timeout_seconds)
        self.worktree_test_timeout = max(_c.MIN_WORKTREE_TEST_TIMEOUT, self.worktree_test_timeout)
        self.max_orphan_worktrees = max(_c.MIN_ORPHAN_WORKTREES, self.max_orphan_worktrees)
        self.git_operation_timeout = max(_c.MIN_GIT_OPERATION_TIMEOUT, self.git_operation_timeout)
        self.max_repair_attempts = max(_c.MIN_REPAIR_ATTEMPTS, self.max_repair_attempts)

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
    beads_backend: str = "bd"  # CLI backend to use: "bd" (Python) or "br" (Rust)

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.priority_weight = max(1, self.priority_weight)
        self.max_workers = max(0, self.max_workers)

@dataclass
class PerformanceThresholdsConfig:
    """Configurable thresholds for the PerformanceMonitor."""
    enabled: bool = True
    max_merge_queue_depth: int = _c.DEFAULT_MAX_MERGE_QUEUE_DEPTH
    max_lock_wait_seconds: float = _c.DEFAULT_MAX_LOCK_WAIT_SECONDS
    max_iteration_seconds: float = _c.DEFAULT_MAX_ITERATION_SECONDS
    min_memory_mb: float = _c.DEFAULT_MIN_MEMORY_MB
    min_success_rate: float = _c.DEFAULT_MIN_SUCCESS_RATE

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.max_merge_queue_depth = max(_c.MIN_MERGE_QUEUE_DEPTH, self.max_merge_queue_depth)
        self.max_lock_wait_seconds = max(_c.MIN_LOCK_WAIT_SECONDS, self.max_lock_wait_seconds)
        self.max_iteration_seconds = max(_c.MIN_ITERATION_SECONDS, self.max_iteration_seconds)
        self.min_memory_mb = max(_c.MIN_MEMORY_MB, self.min_memory_mb)
        self.min_success_rate = max(0.0, min(1.0, self.min_success_rate))

@dataclass
class EconomyModeConfig:
    """Economy mode configuration for routing tasks to appropriate models based on complexity.

    When enabled, routes simple tasks to cheaper/faster models and complex tasks to
    premium models based on complexity tags in work item labels.
    """
    enabled: bool = False
    simple_model: str = "claude-sonnet-4.5"      # Cheapest/fastest for simple tasks
    medium_model: str = "claude-opus-4.5"        # Mid-tier for medium complexity
    complex_model: str = "claude-opus-4.6"       # Premium for complex tasks

    def __post_init__(self) -> None:
        """Validate economy mode configuration."""
        # Ensure model names are non-empty strings when enabled
        if self.enabled:
            if not self.simple_model.strip():
                raise ValueError("simple_model cannot be empty when economy mode is enabled")
            if not self.medium_model.strip():
                raise ValueError("medium_model cannot be empty when economy mode is enabled")
            if not self.complex_model.strip():
                raise ValueError("complex_model cannot be empty when economy mode is enabled")

@dataclass
class ProjectConfig:
    """Top-level project configuration."""
    project_name: str = ""
    models: ModelConfig = field(default_factory=ModelConfig)
    ai_backend: AIBackendConfig = field(default_factory=AIBackendConfig)
    maintenance: MaintenanceConfig = field(default_factory=MaintenanceConfig.defaults)
    model_sync: ModelSyncConfig = field(default_factory=ModelSyncConfig)
    mcp_server: MCPServerConfig = field(default_factory=MCPServerConfig)
    git: GitConfig = field(default_factory=GitConfig)
    preflight_health: PreflightHealthConfig = field(default_factory=PreflightHealthConfig)
    test_data: dict[str, str] = field(default_factory=dict)
    work_artifacts_dir: str | None = None
    max_parallel_agents: int = _c.DEFAULT_MAX_PARALLEL_AGENTS
    command_timeout: int = _c.DEFAULT_COMMAND_TIMEOUT
    gate_agent_enabled: bool = True
    max_gate_rejections_per_item: int = 3  # Max gate rejections before abandoning item
    max_copilot_failure_retries: int = _c.DEFAULT_MAX_COPILOT_FAILURE_RETRIES
    idle_timeout_seconds: int = _c.DEFAULT_IDLE_TIMEOUT_SECONDS
    session_inactivity_timeout: int = _c.DEFAULT_SESSION_INACTIVITY_TIMEOUT
    tool_call_timeout: int = _c.DEFAULT_TOOL_CALL_TIMEOUT
    process_output_timeout: int = _c.DEFAULT_PROCESS_OUTPUT_TIMEOUT
    max_ping_failures: int = _c.DEFAULT_MAX_PING_FAILURES
    circuit_breaker_drain_timeout: int = _c.DEFAULT_CIRCUIT_BREAKER_DRAIN_TIMEOUT
    decomposition_enabled: bool = True
    decomposition_failure_threshold: int = 3
    assignment: AssignmentConfig = field(default_factory=AssignmentConfig)
    economy_mode: EconomyModeConfig = field(default_factory=EconomyModeConfig)
    performance_thresholds: PerformanceThresholdsConfig = field(
        default_factory=PerformanceThresholdsConfig,
    )
    repos: list[RepoConfig] = field(default_factory=list)
    # Startup cleanup configuration
    startup_cleanup_enabled: bool = True
    stale_worktree_commit_threshold: int = 20

    def __post_init__(self) -> None:
        """Clamp values to valid ranges."""
        self.max_parallel_agents = max(_c.MIN_MAX_PARALLEL_AGENTS, self.max_parallel_agents)
        self.command_timeout = max(_c.MIN_COMMAND_TIMEOUT, self.command_timeout)
        self.max_gate_rejections_per_item = max(1, self.max_gate_rejections_per_item)
        self.max_copilot_failure_retries = max(0, self.max_copilot_failure_retries)
        self.idle_timeout_seconds = max(_c.MIN_IDLE_TIMEOUT_SECONDS, self.idle_timeout_seconds)
        self.session_inactivity_timeout = max(_c.MIN_SESSION_INACTIVITY_TIMEOUT, self.session_inactivity_timeout)
        self.tool_call_timeout = max(_c.MIN_TOOL_CALL_TIMEOUT, self.tool_call_timeout)
        self.process_output_timeout = max(_c.MIN_PROCESS_OUTPUT_TIMEOUT, self.process_output_timeout)
        self.max_ping_failures = max(_c.MIN_MAX_PING_FAILURES, self.max_ping_failures)
        self.circuit_breaker_drain_timeout = max(_c.MIN_CIRCUIT_BREAKER_DRAIN_TIMEOUT, self.circuit_breaker_drain_timeout)
        self.decomposition_failure_threshold = max(1, self.decomposition_failure_threshold)
        self.stale_worktree_commit_threshold = max(1, self.stale_worktree_commit_threshold)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a canonical dict suitable for YAML/JSON output."""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> 'ProjectConfig':
        """Create a ProjectConfig from a dictionary (parsed YAML/JSON).

        Warns and skips unrecognized keys instead of crashing, then retries
        in non-strict mode so valid settings are still applied.
        """
        processed_data = dict(data)

        if "model_sync" in processed_data:
            processed_data["model_sync"] = parse_model_sync_config(
                processed_data["model_sync"]
            )

        if "maintenance" in processed_data and "agents" not in processed_data["maintenance"]:
            del processed_data["maintenance"]

        # Migrate removed activity_watchdog config
        if "activity_watchdog" in processed_data:
            aw = processed_data.pop("activity_watchdog")
            if isinstance(aw, dict) and "idle_timeout_seconds" in aw:
                processed_data.setdefault("idle_timeout_seconds", aw["idle_timeout_seconds"])

        cast_types = [bool, int, float]
        try:
            return dacite.from_dict(
                data_class=ProjectConfig,
                data=processed_data,
                config=dacite.Config(strict=True, cast=cast_types),
            )
        except dacite.UnexpectedDataError as e:
            logger.warning(
                "Ignoring unrecognized configuration key(s): %s — "
                "check for typos in your config file.", e,
            )
            return dacite.from_dict(
                data_class=ProjectConfig,
                data=processed_data,
                config=dacite.Config(strict=False, cast=cast_types),
            )


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


# Module-level cached config with thread-safe access
_cached_config: ProjectConfig | None = None
_config_lock = threading.Lock()


def load_config(config_path: Path | None = None) -> ProjectConfig:
    """Load project configuration from explicit path or auto-discovered file.

    Search order: .pokepoke/config.yaml, .yml, .json, then pokepoke.config.json.
    Returns defaults if no config file is found.

    Thread-safe: concurrent calls are serialized via ``_config_lock``.
    """
    global _cached_config

    with _config_lock:
        if _cached_config is not None and config_path is None:
            return _cached_config

    repo_root = _find_repo_root()

    if config_path is not None:
        data = _load_config_file(config_path)
        config = ProjectConfig.from_dict(data)
        with _config_lock:
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
            with _config_lock:
                _cached_config = config
            return config

    # No config file found - use defaults
    config = ProjectConfig()
    with _config_lock:
        _cached_config = config
    return config


def reset_config() -> None:
    """Reset the cached configuration (useful for testing).

    Thread-safe: acquires ``_config_lock`` before clearing the cache.
    """
    global _cached_config
    with _config_lock:
        _cached_config = None


def get_config() -> ProjectConfig:
    """Get the current project configuration (cached)."""
    return load_config()
