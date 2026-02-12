"""Project initialization for PokePoke.

Creates the .pokepoke/ directory with sample config and prompt templates
to help new projects adopt PokePoke quickly.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional


_SAMPLE_CONFIG = """\
# PokePoke Project Configuration
# Customize these settings for your project.
# See https://github.com/AmeliaRose802/PokePoke for documentation.

project_name: {project_name}

# LLM model configuration
models:
  default: claude-opus-4.6
  fallback: claude-sonnet-4.5

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


def init_project(
    target_dir: Optional[Path] = None,
    project_name: Optional[str] = None,
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
        print(f"⚠️  {config_path} already exists. Use --force to overwrite.")
        return False

    # Create directories
    prompts_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 Created {pokepoke_dir}/")

    # Write config
    config_content = _SAMPLE_CONFIG.format(project_name=project_name)
    config_path.write_text(config_content, encoding="utf-8")
    print(f"📄 Created {config_path.relative_to(root)}")

    # Write sample prompt template
    beads_path = prompts_dir / "beads-item.md"
    if not beads_path.exists() or force:
        beads_path.write_text(_BEADS_ITEM_TEMPLATE, encoding="utf-8")
        print(f"📄 Created {beads_path.relative_to(root)}")

    print(f"\n✅ PokePoke initialized for '{project_name}'")
    print("\nNext steps:")
    print("  1. Edit .pokepoke/config.yaml to customize settings")
    print("  2. Add prompt templates in .pokepoke/prompts/")
    print("  3. Run: python -m pokepoke.orchestrator --interactive")
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
