"""Multi-repo configuration validation and CLI parsing.

Provides startup validation for repo configs (paths, beads availability,
copilot instructions) and a CLI argument parser for ``--repos`` specs.
"""

from dataclasses import dataclass, field
from pathlib import Path

from .config import RepoConfig
from .constants import BEADS_DIR


@dataclass
class RepoValidationResult:
    """Result of validating a single RepoConfig."""
    repo_path: str
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _check_beads_available(repo_path: Path, beads_db_path: str | None) -> tuple[bool, str | None]:
    """Check whether beads is available for a repo.

    Returns (available, error_message).
    """
    if beads_db_path:
        db = Path(beads_db_path)
        if not db.is_dir():
            return False, f"Explicit beads_db_path does not exist: {beads_db_path}"
        return True, None

    # Auto-discover: look for .beads directory in the repo
    beads_dir = repo_path / BEADS_DIR
    if beads_dir.is_dir():
        return True, None
    return False, f"No {BEADS_DIR} directory found in {repo_path} (set beads_db_path explicitly or run 'bd init')"


def validate_repo_config(repo: RepoConfig) -> RepoValidationResult:
    """Validate a single RepoConfig entry.

    Checks:
    - path exists and is a directory
    - beads database is available (auto-discovered or explicit)
    - copilot_instructions_path exists if specified
    - quality_gate_overrides have valid values
    """
    result = RepoValidationResult(repo_path=repo.path, valid=True)

    if not repo.path:
        result.valid = False
        result.errors.append("Repo path is empty")
        return result

    repo_path = Path(repo.path)
    if not repo_path.is_dir():
        result.valid = False
        result.errors.append(f"Repo path does not exist: {repo.path}")
        return result

    # Beads availability
    beads_ok, beads_err = _check_beads_available(repo_path, repo.beads_db_path)
    if not beads_ok:
        result.warnings.append(beads_err or "Beads not available")

    # Copilot instructions path
    if repo.copilot_instructions_path:
        instr_path = Path(repo.copilot_instructions_path)
        if not instr_path.is_absolute():
            instr_path = repo_path / instr_path
        if not instr_path.is_file():
            result.warnings.append(
                f"Copilot instructions path does not exist: {repo.copilot_instructions_path}"
            )

    # Quality gate overrides sanity
    if repo.quality_gate_overrides:
        qg = repo.quality_gate_overrides
        if qg.coverage_threshold is not None and qg.coverage_threshold <= 0:
            result.warnings.append("coverage_threshold is <= 0, effectively disabling coverage checks")

    return result


def validate_repo_configs(repos: list[RepoConfig]) -> list[RepoValidationResult]:
    """Validate all configured repositories at startup.

    Returns a list of validation results. Disabled repos are skipped
    with a valid result (no errors).
    """
    results: list[RepoValidationResult] = []
    for repo in repos:
        if not repo.enabled:
            results.append(RepoValidationResult(repo_path=repo.path, valid=True))
            continue
        results.append(validate_repo_config(repo))
    return results


def _split_repo_entry(entry: str) -> list[str]:
    """Split a repo CLI entry into ``[path, option, ...]``.

    Handles Windows drive-letter colons (e.g. ``C:\\repo``) by only splitting
    on colons that separate ``key=value`` options from the path.  A colon
    immediately after a single ASCII letter **and** followed by ``/`` or ``\\``
    is treated as part of the path (drive letter) and not a separator.
    """
    # Fast path: no colon at all → plain path
    if ":" not in entry:
        return [entry]

    # Detect Windows drive prefix (e.g. "C:\")
    has_drive = (
        len(entry) >= 3
        and entry[0].isalpha()
        and entry[1] == ":"
        and entry[2] in ("/", "\\")
    )

    if has_drive:
        # Preserve drive prefix; split the rest on ":"
        rest = entry[2:]  # everything after "X:"
        parts = rest.split(":")
        # Re-attach the drive letter to the first segment
        parts[0] = entry[:2] + parts[0]
        return parts

    return entry.split(":")


def parse_repos_cli(repos_arg: list[str]) -> list[RepoConfig]:
    """Parse ``--repos`` CLI arguments into RepoConfig objects.

    Each entry can be:
    - A plain path: ``/path/to/repo``
    - A path with weight: ``/path/to/repo:weight=5``
    - A path with multiple options: ``/path/to/repo:weight=5:max_workers=2``

    Supported options after the path (colon-separated key=value pairs):
    - ``weight`` — maps to ``priority_weight``
    - ``max_workers`` — per-repo worker cap
    - ``disabled`` — set to ``true`` / ``1`` to disable

    Returns:
        List of RepoConfig objects.
    """
    configs: list[RepoConfig] = []
    for entry in repos_arg:
        parts = _split_repo_entry(entry)
        path = parts[0].strip()
        kwargs: dict[str, str] = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                kwargs[key.strip()] = value.strip()

        weight = int(kwargs.get("weight", "1"))
        max_w = int(kwargs.get("max_workers", "0"))
        disabled = kwargs.get("disabled", "").lower() in ("true", "1", "yes")

        configs.append(RepoConfig(
            path=path,
            priority_weight=weight,
            max_workers=max_w,
            enabled=not disabled,
        ))
    return configs
