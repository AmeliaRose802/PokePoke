"""Project configuration system for PokePoke.

Loads project-specific settings from .pokepoke/config.yaml, allowing PokePoke
to be used generically on any project without hardcoded values.
"""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore[import-untyped]
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

import json


@dataclass
class ModelConfig:
    """LLM model configuration."""
    default: str = "claude-opus-4.6"
    fallback: str = "claude-sonnet-4.5"
    candidate_models: List[str] = field(default_factory=list)


@dataclass
class MaintenanceAgentConfig:
    """Configuration for a single maintenance agent."""
    name: str = ""
    prompt_file: str = ""
    frequency: int = 5
    needs_worktree: bool = False
    merge_changes: bool = True
    model: Optional[str] = None
    enabled: bool = True


@dataclass
class MaintenanceConfig:
    """Maintenance agent scheduling configuration."""
    agents: List[MaintenanceAgentConfig] = field(default_factory=list)

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
        ])


@dataclass
class MpcServerConfig:
    """MCP server configuration."""
    enabled: bool = False
    restart_script: Optional[str] = None
    name: Optional[str] = None


@dataclass
class GitConfig:
    """Git-related configuration."""
    default_branch: Optional[str] = None
    fallback_branch: str = "master"

    def get_preferred_branch(self) -> Optional[str]:
        """Get the preferred branch, auto-detecting from environment if not set."""
        if self.default_branch:
            return self.default_branch
        # Auto-detect: try git config or environment
        username = _detect_git_username()
        if username:
            return f"{username}/dev"
        return None


@dataclass
class TestDataEntry:
    """A single piece of test data for prompt templates."""
    key: str = ""
    value: str = ""
    description: str = ""


@dataclass
class ProjectConfig:
    """Top-level project configuration."""
    project_name: str = ""
    models: ModelConfig = field(default_factory=ModelConfig)
    maintenance: MaintenanceConfig = field(default_factory=MaintenanceConfig.defaults)
    mcp_server: MpcServerConfig = field(default_factory=MpcServerConfig)
    git: GitConfig = field(default_factory=GitConfig)
    test_data: Dict[str, str] = field(default_factory=dict)
    work_artifacts_dir: Optional[str] = None

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'ProjectConfig':
        """Create a ProjectConfig from a dictionary (parsed YAML/JSON)."""
        config = ProjectConfig()

        config.project_name = data.get("project_name", "")

        # Models
        models_data = data.get("models", {})
        config.models = ModelConfig(
            default=models_data.get("default", "claude-opus-4.6"),
            fallback=models_data.get("fallback", "claude-sonnet-4.5"),
            candidate_models=models_data.get("candidate_models", []),
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
                )
                for a in agents_data
            ])
        # else: keep defaults from field(default_factory=...)

        return config


def _detect_git_username() -> Optional[str]:
    """Try to detect the git username from git config."""
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, encoding='utf-8', timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            email = result.stdout.strip()
            # Extract username from email (part before @)
            return email.split("@")[0]
    except Exception:
        pass
    return None


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


def _load_config_file(config_path: Path) -> Dict[str, Any]:
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
_cached_config: Optional[ProjectConfig] = None


def load_config(config_path: Optional[Path] = None) -> ProjectConfig:
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
