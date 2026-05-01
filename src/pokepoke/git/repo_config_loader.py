"""Multi-repo configuration validation and CLI parsing.

Provides startup validation for repo configs (paths, beads availability,
copilot instructions) and a CLI argument parser for ``--repos`` specs.
"""

from dataclasses import dataclass, field
from pathlib import Path

from pokepoke.config import RepoConfig
from pokepoke.utils.constants import BEADS_DIR


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
