"""Cleanup agent invocation utilities."""

import subprocess
from pathlib import Path

from pokepoke.copilot import invoke_copilot
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult
from pokepoke.git_operations import verify_main_repo_clean, commit_all_changes
from pokepoke import terminal_ui

def aggregate_cleanup_stats(result_stats: AgentStats | None, cleanup_stats: AgentStats | None) -> None:
    """Aggregate cleanup agent stats into result stats."""
    if cleanup_stats and result_stats:
        result_stats.accumulate(cleanup_stats)


def run_cleanup_loop(item: BeadsWorkItem, result: CopilotResult, repo_root: Path, cwd: str | None = None) -> tuple[bool, int]:
    """Run cleanup loop to commit changes and fix validation failures."""
    cleanup_agent_runs = 0
    cleanup_attempt = 0

    # Check for uncommitted changes, excluding beads-only changes
    try:
        is_clean, uncommitted, non_beads_changes = verify_main_repo_clean(cwd=cwd)
    except Exception as e:
        print(f"\n⚠️  Error checking git status: {e}")
        return False, cleanup_agent_runs

    while result.success and not is_clean:
        cleanup_attempt += 1
        print(f"\n⚠️  Uncommitted non-beads changes detected (cleanup attempt {cleanup_attempt})")
        names = [f.split()[1] if len(f.split()) > 1 else f for f in non_beads_changes]
        preview = ", ".join(names[:5])
        suffix = "..." if len(names) > 5 else ""
        print(f"   Files: {preview}{suffix}")

        commit_success, commit_error = commit_all_changes(f"Work on {item.id}", cwd=cwd)

        if commit_success:
            print("✅ Changes committed successfully (validation passed)")
            break
        else:
            print("\n❌ Commit failed - validation errors:")
            print(f"   {commit_error}")

        print("\n🧹 Invoking cleanup agent to fix validation errors...")
        cleanup_agent_runs += 1
        # Extract file paths from status lines (e.g. " M file.py" -> "file.py")
        file_paths = [f.split()[-1] if f.split() else f for f in non_beads_changes]
        cleanup_success, cleanup_stats = invoke_cleanup_agent(
            item, repo_root, cwd=cwd, modified_files=file_paths,
        )

        aggregate_cleanup_stats(result.stats, cleanup_stats)

        if not cleanup_success:
            print("\n❌ Cleanup agent failed")
            result.success = False
            result.error = "Cleanup agent failed to fix issues"
            break

        # Re-check status after cleanup
        try:
            is_clean, uncommitted, non_beads_changes = verify_main_repo_clean(cwd=cwd)
        except Exception as e:
            print(f"\n⚠️  Error checking git status after cleanup: {e}")
            result.success = False
            result.error = f"Git status check failed: {e}"
            break

    return result.success, cleanup_agent_runs


def get_pokepoke_prompts_dir() -> Path:
    """Get the prompts directory from the PokePoke installation."""
    # Prompts are relative to this file's location in the PokePoke package
    # This file is at: PokePoke/src/pokepoke/cleanup_agents.py
    # Prompts are at: PokePoke/.pokepoke/prompts/
    pokepoke_root = Path(__file__).parent.parent.parent
    prompts_dir = pokepoke_root / ".pokepoke" / "prompts"

    if not prompts_dir.exists():
        raise FileNotFoundError(
            f"PokePoke prompts directory not found at {prompts_dir}. "
            f"Make sure you have the .pokepoke/prompts/ directory in your PokePoke installation."
        )

    return prompts_dir


def load_prompt_file(filename: str) -> str | None:
    """Load a prompt file from the PokePoke prompts directory.

    Returns the file contents, or None if the file cannot be found
    (prints an error message in that case).
    """
    try:
        prompts_dir = get_pokepoke_prompts_dir()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return None

    prompt_path = prompts_dir / filename
    if not prompt_path.exists():
        print(f"❌ Prompt not found at {prompt_path}")
        return None

    return prompt_path.read_text(encoding='utf-8')


def _get_current_git_context(cwd: str | None = None) -> tuple[str, str, bool]:
    """Get current git context (directory, branch, is_worktree)."""
    current_dir = cwd or str(Path.cwd())

    # Get current branch
    try:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
            errors='replace',
            cwd=cwd
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    except Exception:
        current_branch = "unknown"

    # Determine if we're in a worktree
    try:
        worktree_result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            errors='replace',
            cwd=cwd
        )
        is_worktree = worktree_result.returncode == 0 and worktree_result.stdout.strip() == "true"
    except Exception:
        is_worktree = False

    return current_dir, current_branch, is_worktree


def invoke_cleanup_agent(item: BeadsWorkItem, repo_root: Path, cwd: str | None = None, modified_files: list[str] | None = None) -> tuple[bool, AgentStats | None]:
    """Invoke cleanup agent to commit uncommitted changes."""
    terminal_ui.ui.set_current_agent("Cleanup Agent")

    # Register cleanup agent in the Agents panel
    agent_id = f"{item.id}-cleanup"
    terminal_ui.ui.push_agent_status(
        agent_id, "Cleanup Agent", iteration=1, status="running",
        work_item_id=item.id, work_item_title=item.title,
        modified_files=modified_files,
    )

    cleanup_prompt_template = load_prompt_file("cleanup.md")
    if cleanup_prompt_template is None:
        terminal_ui.ui.push_agent_status(agent_id, "Cleanup Agent", iteration=1, status="failed")
        return False, None

    # Get current context information
    current_dir, current_branch, is_worktree = _get_current_git_context(cwd=cwd)

    # Replace placeholders in template
    cleanup_prompt_template = cleanup_prompt_template.replace("{cwd}", current_dir)
    cleanup_prompt_template = cleanup_prompt_template.replace("{branch}", current_branch)
    cleanup_prompt_template = cleanup_prompt_template.replace("{is_worktree}", str(is_worktree))

    work_item_context = f"""
# Work Item Being Cleaned Up

**ID:** {item.id}
**Title:** {item.title}
**Type:** {item.issue_type}
**Priority:** {item.priority}
**Status:** {item.status}

**Description:**
{item.description}
"""

    if item.labels:
        work_item_context += f"\n**Labels:** {', '.join(item.labels)}\n"

    cleanup_prompt = f"{work_item_context}\n\n---\n\n{cleanup_prompt_template}"

    cleanup_item = BeadsWorkItem(
        id=f"{item.id}-cleanup",
        title=f"Cleanup for {item.id}",
        description=cleanup_prompt,
        status="in_progress",
        priority=0,
        issue_type="task",
        labels=["cleanup", "automated"]
    )

    print("\n🧹 Invoking cleanup agent...")

    # Route all output to the cleanup agent's log buffer
    try:
        from pokepoke.metrics_context import agent_type_context
        with terminal_ui.ui.agent_output_for(agent_id):
            with agent_type_context("cleanup"):
                copilot_result = invoke_copilot(cleanup_item, prompt=cleanup_prompt, cwd=cwd)

        # Update agent status based on result
        status = "success" if copilot_result.success else "failed"
        terminal_ui.ui.push_agent_status(agent_id, "Cleanup Agent", iteration=1, status=status)

        return copilot_result.success, copilot_result.stats
    except Exception:
        terminal_ui.ui.push_agent_status(agent_id, "Cleanup Agent", iteration=1, status="failed")
        raise


def invoke_merge_conflict_cleanup_agent(
    item: BeadsWorkItem,
    repo_root: Path,
    error_msg: str,
    unmerged_files: list[str] | None = None,
    cwd: str | None = None
) -> tuple[bool, AgentStats | None]:
    """Invoke cleanup agent to resolve merge conflicts.

    Args:
        item: The work item being processed
        repo_root: Path to the repository root
        error_msg: Description of the merge error
        unmerged_files: Optional list of files with merge conflicts
        cwd: Optional working directory for the Copilot process.
    """
    terminal_ui.ui.set_current_agent("Merge Conflict Cleanup")

    # Register merge conflict cleanup agent in the Agents panel
    agent_id = f"{item.id}-merge-fix"
    terminal_ui.ui.push_agent_status(
        agent_id, "Merge Conflict Cleanup", iteration=1, status="running",
        work_item_id=item.id, work_item_title=item.title,
    )

    from pokepoke.git_operations import is_merge_in_progress, get_unmerged_files as git_get_unmerged

    cleanup_prompt_template = load_prompt_file("merge-conflict-cleanup.md")
    if cleanup_prompt_template is None:
        # Fallback to standard cleanup
        print("⚠️ Falling back to standard cleanup agent")
        terminal_ui.ui.push_agent_status(agent_id, "Merge Conflict Cleanup", iteration=1, status="failed")
        return invoke_cleanup_agent(item, repo_root)

    # Get current context information
    current_dir, current_branch, is_worktree = _get_current_git_context(cwd=cwd)

    # Get merge state info
    is_merging = is_merge_in_progress()
    if unmerged_files is None:
        unmerged_files = git_get_unmerged()

    # Build conflict files section
    conflict_files_section = ""
    if unmerged_files:
        lines = [f"- `{f}`" for f in unmerged_files]
        conflict_files_section = "\n**Conflicted Files:**\n" + "\n".join(lines) + "\n"

    # Replace placeholders in template
    cleanup_prompt_template = cleanup_prompt_template.replace("{cwd}", current_dir)
    cleanup_prompt_template = cleanup_prompt_template.replace("{branch}", current_branch)
    cleanup_prompt_template = cleanup_prompt_template.replace("{is_worktree}", str(is_worktree))
    cleanup_prompt_template = cleanup_prompt_template.replace("{merge_error}", error_msg)
    cleanup_prompt_template = cleanup_prompt_template.replace("{worktree_path}", f"worktrees/task-{item.id}")
    cleanup_prompt_template = cleanup_prompt_template.replace("{is_merge_in_progress}", str(is_merging))
    cleanup_prompt_template = cleanup_prompt_template.replace("{conflict_files}", conflict_files_section)
    cleanup_prompt_template = cleanup_prompt_template.replace("{conflict_count}", str(len(unmerged_files)))

    work_item_context = f"""
# Work Item That Failed to Merge

**ID:** {item.id}
**Title:** {item.title}
**Type:** {item.issue_type}
**Priority:** {item.priority}
**Status:** {item.status}

**Description:**
{item.description}

**Merge State:**
- Merge in progress: {is_merging}
- Conflicted files: {len(unmerged_files)}
{conflict_files_section}

**Merge Error:**
{error_msg}
"""

    if item.labels:
        work_item_context += f"\n**Labels:** {', '.join(item.labels)}\n"

    cleanup_prompt = f"{work_item_context}\n\n---\n\n{cleanup_prompt_template}"

    cleanup_item = BeadsWorkItem(
        id=f"{item.id}-merge-fix",
        title=f"Fix merge conflicts for {item.id}",
        description=cleanup_prompt,
        status="in_progress",
        priority=0,
        issue_type="task",
        labels=["cleanup", "merge-conflict"]
    )

    print("\n🧹 Invoking merge conflict cleanup agent...")
    if unmerged_files:
        print(f"   Conflicted files: {len(unmerged_files)}")
        for f in unmerged_files[:5]:
            print(f"      - {f}")
        if len(unmerged_files) > 5:
            print(f"      ... and {len(unmerged_files) - 5} more")

    # Route all output to the merge conflict cleanup agent's log buffer
    try:
        from pokepoke.metrics_context import agent_type_context
        with terminal_ui.ui.agent_output_for(agent_id):
            with agent_type_context("merge_conflict_cleanup"):
                copilot_result = invoke_copilot(cleanup_item, prompt=cleanup_prompt, cwd=cwd)

        # Update agent status based on result
        status = "success" if copilot_result.success else "failed"
        terminal_ui.ui.push_agent_status(agent_id, "Merge Conflict Cleanup", iteration=1, status=status)

        return copilot_result.success, copilot_result.stats
    except Exception:
        terminal_ui.ui.push_agent_status(agent_id, "Merge Conflict Cleanup", iteration=1, status="failed")
        raise
