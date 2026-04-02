"""Project initialization for PokePoke.

Creates the .pokepoke/ directory with sample config and prompt templates
to help new projects adopt PokePoke quickly.
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from pokepoke.utils.constants import BEADS_DIR

logger = logging.getLogger(__name__)

_SAMPLE_CONFIG = """\
# PokePoke Project Configuration
# Customize these settings for your project.
# See https://github.com/AmeliaRose802/PokePoke for documentation.

project_name: {project_name}

# LLM model configuration
models:
  default: claude-opus-4.6
  fallback: claude-sonnet-4.5

# Copilot model discovery sync (creates beads items for new beta models)
model_sync:
  enabled: true
  interval_minutes: 60
  beta_only: true
  include_preview: true
  prune_unavailable: false
  create_beads_items: true
  issue_type: task
  priority: 2
  labels: [model, beta, copilot]

# Git branch configuration
# If not set, auto-detects from git user.email
git:
  # default_branch: your-username/dev
  fallback_branch: master

# MCP server integration (optional)
# Set enabled: true if your project uses an MCP server
mcp_server:
  enabled: false
  # restart_script: scripts/Restart-MCPServer.ps1
  # name: My MCP Server

  # Memory server (persistent agent knowledge across sessions)
  memory_enabled: false
  # memory_file_path: null  # Auto-detected: .pokepoke/memory.jsonl
  # confidence_decay_days: 30  # Days before observations are considered stale

# Maintenance agent scheduling
# Each agent runs every N work items completed.
maintenance:
  agents:
    - name: Tech Debt
      prompt_file: tech-debt.md
      frequency: 5
      needs_worktree: false
      enabled: true

    - name: Janitor
      prompt_file: janitor.md
      frequency: 2
      needs_worktree: true
      merge_changes: true
      enabled: true

    - name: Backlog Cleanup
      prompt_file: backlog-cleanup.md
      frequency: 7
      needs_worktree: true
      merge_changes: false
      enabled: true

    - name: Worktree Cleanup
      prompt_file: worktree-cleanup.md
      frequency: 4
      needs_worktree: false
      enabled: true

    - name: Model Sync
      prompt_file: ""
      frequency: 1
      needs_worktree: false
      merge_changes: false
      enabled: true

# Project-specific test data for prompt templates (optional)
# test_data:
#   a test url: "https://example.com/test"
#   a test id: "test-123"

# Work artifacts directory (optional)
# work_artifacts_dir: work_artifacts
"""

_BEADS_ITEM_TEMPLATE = """\
# Work Item: {{title}}

**ID:** {{item_id}}
**Type:** {{issue_type}}
**Priority:** {{priority}}
{{#labels}}
**Labels:** {{labels}}
{{/labels}}

## Description

{{description}}

## Instructions

Complete the work described above. Follow project conventions and
ensure all tests pass before finishing.

{{#test_data_section}}
## Test Data

{{test_data_section}}
{{/test_data_section}}
"""

_SEED_BEADS_ITEMS: tuple[dict[str, object], ...] = (
    {
        "title": "Setup pre-commit hooks (quality gates, linting, test runner)",
        "description": (
            "Add pre-commit hooks that run quality gates, linting, and targeted tests. "
            "Document how to install and run the hooks so agents follow the same workflow."
        ),
        "labels": ("setup", "quality-gates"),
        "priority": "3",
    },
    {
        "title": "Create copilot-instructions.md and repo instruction files",
        "description": (
            "Add .github/copilot-instructions.md plus any supporting instruction files "
            "so Copilot agents understand repository conventions and quality gates."
        ),
        "labels": ("setup", "copilot-instructions"),
        "priority": "3",
    },
)


def _load_existing_beads_titles(root: Path) -> set[str]:
    issues_path = root / BEADS_DIR / "issues.jsonl"
    if not issues_path.exists():
        return set()

    titles: set[str] = set()
    with issues_path.open(encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            title = data.get("title") if isinstance(data, dict) else None
            if isinstance(title, str) and title.strip():
                titles.add(title.strip().lower())
    return titles


def _seed_setup_beads_items(root: Path) -> None:
    if not (root / BEADS_DIR).exists():
        logger.warning("ℹ️  Beads not initialized yet; skipping setup item seeding.")
        return
    if not shutil.which("bd"):
        logger.warning("ℹ️  Beads CLI not found; skipping setup item seeding.")
        return

    existing_titles = _load_existing_beads_titles(root)
    for item in _SEED_BEADS_ITEMS:
        title = str(item["title"])
        if title.strip().lower() in existing_titles:
            logger.info(f"ℹ️  Beads item already exists: {title}")
            continue

        labels = item.get("labels", ())
        label_value = ",".join(labels) if isinstance(labels, (tuple, list)) else ""
        cmd = [
            "bd",
            "create",
            title,
            "--type",
            "task",
            "--priority",
            str(item.get("priority", "3")),
            "--description",
            str(item.get("description", "")),
            "--json",
        ]
        if label_value:
            cmd.extend(["--labels", label_value])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(root),
                check=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            logger.warning(f"⚠️  Timed out creating beads item: {title}")
            continue
        except subprocess.CalledProcessError as exc:
            error_msg = exc.stderr.strip() if exc.stderr else f"exit code {exc.returncode}"
            logger.error(f"⚠️  Failed to create beads item '{title}': {error_msg}")
            continue

        created_id = None
        try:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict):
                created_id = payload.get("id")
        except json.JSONDecodeError:
            created_id = None

        if isinstance(created_id, str) and created_id:
            logger.info(f"✅ Created beads item {created_id}: {title}")
        else:
            logger.info(f"✅ Created beads item: {title}")


def init_project(
    target_dir: Path | None = None,
    project_name: str | None = None,
    force: bool = False,
) -> bool:
    """Initialize a .pokepoke directory with sample config and templates.

    Args:
        target_dir: Directory to create .pokepoke/ in. Defaults to cwd.
        project_name: Project name for config. Defaults to directory name.
        force: Overwrite existing files if True.

    Returns:
        True if initialization succeeded.
    """
    root = target_dir or Path.cwd()
    pokepoke_dir = root / ".pokepoke"
    prompts_dir = pokepoke_dir / "prompts"

    if not project_name:
        project_name = root.name

    # Check for existing directory
    config_path = pokepoke_dir / "config.yaml"
    if config_path.exists() and not force:
        logger.warning(f"⚠️  {config_path} already exists. Use --force to overwrite.")
        return False

    # Create directories
    prompts_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 Created {pokepoke_dir}/")

    # Write config
    config_content = _SAMPLE_CONFIG.format(project_name=project_name)
    config_path.write_text(config_content, encoding="utf-8")
    logger.info(f"📄 Created {config_path.relative_to(root)}")

    # Write sample prompt template
    beads_path = prompts_dir / "beads-item.md"
    if not beads_path.exists() or force:
        beads_path.write_text(_BEADS_ITEM_TEMPLATE, encoding="utf-8")
        logger.info(f"📄 Created {beads_path.relative_to(root)}")

    _seed_setup_beads_items(root)

    logger.info(f"\n✅ PokePoke initialized for '{project_name}'")
    logger.info("\nNext steps:")
    logger.info("  1. Edit .pokepoke/config.yaml to customize settings")
    logger.info("  2. Add prompt templates in .pokepoke/prompts/")
    logger.info("  3. Run: python -m pokepoke.orchestration.orchestrator --interactive")
    logger.info("     (Add --agent-name Janitor to pin a custom agent name)")
    return True


def main() -> int:
    """CLI entry point for pokepoke init."""
    parser = argparse.ArgumentParser(
        description="Initialize PokePoke for a new project"
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="Target directory (default: current directory)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Project name (default: directory name)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config files",
    )
    args = parser.parse_args()
    ok = init_project(
        target_dir=args.dir,
        project_name=args.name,
        force=args.force,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
