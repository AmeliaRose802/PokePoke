"""Project configuration system for PokePoke.

Thin facade: dataclass types live in ``config_types``; this module adds
file-discovery, caching and thread-safe access.  All public names are
re-exported so existing ``from pokepoke.config import …`` statements
continue to work unchanged.
"""
import json
import logging
import threading
from pathlib import Path
from typing import Any

# Re-export every public type so callers keep using ``from pokepoke.config import …``
from pokepoke.config_types import (  # noqa: F401
    DEFAULT_MODEL,
    FALLBACK_MODEL,
    GIT_OPERATION_TIMEOUT,
    LOCK_TIMEOUT_SECONDS,
    MAX_ORPHAN_WORKTREES,
    MIN_WORKTREE_TIMEOUT,
    WORKTREE_TEST_TIMEOUT,
    AIBackendConfig,
    AssignmentConfig,
    AssignmentRule,
    AssignmentRuleMatch,
    EconomyModeConfig,
    GitConfig,
    MaintenanceAgentConfig,
    MaintenanceConfig,
    MCPServerConfig,
    ModelConfig,
    PerformanceThresholdsConfig,
    PostMortemConfig,
    PreflightHealthConfig,
    ProjectConfig,
    QualityGateOverrides,
    RepoConfig,
    StateBranchConfig,
    WarmSessionConfig,
)
from pokepoke.config_validation import ConfigError  # noqa: F401
from pokepoke.models.model_sync_config import ModelSyncConfig  # noqa: F401
from pokepoke.otel_config import OtelConfig  # noqa: F401

logger = logging.getLogger(__name__)

try:
    import yaml  # type: ignore[import-untyped]
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


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
    """Load project configuration from explicit path or auto-discovered file."""
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
    """Reset the cached configuration. Thread-safe."""
    global _cached_config
    with _config_lock:
        _cached_config = None


def get_config() -> ProjectConfig:
    """Get the current project configuration (cached)."""
    return load_config()
