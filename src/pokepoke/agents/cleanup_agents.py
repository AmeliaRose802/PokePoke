"""Cleanup agent invocation utilities."""

import logging
import time
from pathlib import Path

from pokepoke.desktop import terminal_ui
from pokepoke.git.git_helpers import run_git
from pokepoke.git.git_operations import commit_all_changes, verify_main_repo_clean
from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.types import AgentStats, BeadsWorkItem
from pokepoke.types_agent import CopilotResult
from pokepoke.utils.constants import (
    CLEANUP_AGENT_TIMEOUT,
    CLEANUP_AGGREGATE_TIMEOUT,
    STATUS_IN_PROGRESS,
    WORKTREE_DIR,
    WORKTREE_TASK_PREFIX,
)
from pokepoke.worktrees.coordination import merge_lock_active

logger = logging.getLogger(__name__)

def aggregate_cleanup_stats(result_stats: AgentStats | None, cleanup_stats: AgentStats | None) -> None:
    """Aggregate cleanup agent stats into result stats."""
    if cleanup_stats and result_stats:
        result_stats.accumulate(cleanup_stats)


def run_cleanup_loop(
    item: BeadsWorkItem,
    result: CopilotResult,
    cwd: str | None = None,
    parent_agent_id: str | None = None
) -> tuple[bool, int]:
    """Run cleanup loop to commit changes and fix validation failures."""
    cleanup_agent_runs = 0
    cleanup_attempt = 0
    loop_start = time.monotonic()
    previous_errors: list[str] = []

    # Check for uncommitted changes, excluding beads-only changes
    try:
        is_clean, _uncommitted, non_beads_changes = verify_main_repo_clean(cwd=cwd)
    except Exception as e:
        # Transient git contention can cause git status to fail; treat as clean.
        logger.warning(f"Error checking git status (treating as clean): {e}", exc_info=True)
        logger.error(f"\n⚠️  Error checking git status: {e}")
        return True, cleanup_agent_runs

    while result.success and not is_clean:
        # Enforce aggregate timeout across all cleanup attempts
        elapsed = time.monotonic() - loop_start
        if elapsed >= CLEANUP_AGGREGATE_TIMEOUT:
            logger.warning(
                f"Cleanup aggregate timeout reached ({elapsed:.0f}s >= {CLEANUP_AGGREGATE_TIMEOUT:.0f}s)"
            )
            logger.info(f"\n⏰ Cleanup aggregate timeout reached ({elapsed:.0f}s) - aborting cleanup loop")
            result.success = False
            result.error = f"Cleanup aggregate timeout ({CLEANUP_AGGREGATE_TIMEOUT:.0f}s) exceeded"
            break

        cleanup_attempt += 1
        logger.warning(f"\n⚠️  Uncommitted non-beads changes detected (cleanup attempt {cleanup_attempt})")
        names = [f.split()[1] if len(f.split()) > 1 else f for f in non_beads_changes]
        preview = ", ".join(names[:5])
        suffix = "..." if len(names) > 5 else ""
        logger.info(f"   Files: {preview}{suffix}")

        commit_success, commit_error = commit_all_changes(f"Work on {item.id}", cwd=cwd, tracked_only=True)

        if commit_success:
            logger.info("✅ Changes committed successfully (validation passed)")
            break
        else:
            logger.error("\n❌ Commit failed - validation errors:")
            logger.error(f"   {commit_error}")

            # Detect recurring errors: if same error seen before, short-circuit
            if commit_error and commit_error in previous_errors:
                logger.warning(f"Recurring commit error detected, short-circuiting cleanup: {commit_error}")
                logger.error("\n🔁 Same error recurring across attempts - short-circuiting cleanup")
                result.success = False
                result.error = f"Recurring cleanup error (short-circuited): {commit_error}"
                break
            if commit_error:
                previous_errors.append(commit_error)

        logger.error("\n🧹 Invoking cleanup agent to fix validation errors...")
        cleanup_agent_runs += 1
        # Extract file paths from status lines (e.g. " M file.py" -> "file.py")
        file_paths = [f.split()[-1] if f.split() else f for f in non_beads_changes]
        cleanup_success, cleanup_stats = invoke_cleanup_agent(
            item,
            cwd=cwd,
            modified_files=file_paths,
            parent_agent_id=parent_agent_id,
        )

        aggregate_cleanup_stats(result.stats, cleanup_stats)

        if not cleanup_success:
            logger.error("\n❌ Cleanup agent failed")
            result.success = False
            result.error = "Cleanup agent failed to fix issues"
            break

        # Re-check status after cleanup
        try:
            is_clean, _uncommitted, non_beads_changes = verify_main_repo_clean(cwd=cwd)
        except Exception as e:
            logger.error(f"\n⚠️  Error checking git status after cleanup: {e}")
            result.success = False
            result.error = f"Git status check failed: {e}"
            break

    return result.success, cleanup_agent_runs


def get_pokepoke_prompts_dir() -> Path:
    """Get the prompts directory from the PokePoke installation."""
    # Walk upward from this file to find the repo root containing .pokepoke/prompts/
    # This file is at: PokePoke/src/pokepoke/agents/cleanup_agents.py
    current = Path(__file__).resolve().parent
    for _ in range(10):  # reasonable limit
        prompts_dir = current / ".pokepoke" / "prompts"
        if prompts_dir.exists():
            return prompts_dir
        if current == current.parent:
            break
        current = current.parent

    raise FileNotFoundError(
        f"PokePoke prompts directory not found (searched up from {Path(__file__).parent}). "
        f"Make sure .pokepoke/prompts/ exists in your PokePoke installation.")


def load_prompt_file(filename: str) -> str | None:
    """Load a prompt file from the PokePoke prompts directory, or None on failure."""
    try:
        prompts_dir = get_pokepoke_prompts_dir()
    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        return None

    prompt_path = prompts_dir / filename
    if not prompt_path.exists():
        logger.error(f"❌ Prompt not found at {prompt_path}")
        return None

    return prompt_path.read_text(encoding='utf-8')


def _git_output(args: list[str], cwd: str | None) -> str | None:
    """Run a git command and return stripped stdout, or None on failure."""
    try:
        r = run_git(args, timeout=10, cwd=cwd, check=False)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        logger.debug("Git command failed: %s", args, exc_info=True)
        return None


def _get_current_git_context(cwd: str | None = None) -> tuple[str, str, bool]:
    """Get current git context (directory, branch, is_worktree)."""
    current_dir = cwd or str(Path.cwd())
    current_branch = _git_output(["git", "branch", "--show-current"], cwd) or "unknown"
    is_worktree = _git_output(["git", "rev-parse", "--is-inside-work-tree"], cwd) == "true"
    return current_dir, current_branch, is_worktree


def _apply_base_template_vars(template: str, current_dir: str, current_branch: str, is_worktree: bool) -> str:
    """Apply common template variable replacements."""
    return (template.replace("{cwd}", current_dir)
            .replace("{branch}", current_branch)
            .replace("{is_worktree}", str(is_worktree)))


def _build_work_item_context(item: BeadsWorkItem, heading: str, extra: str = "") -> str:
    """Build markdown context block for a work item."""
    context = (f"\n# {heading}\n\n**ID:** {item.id}\n**Title:** {item.title}\n"
               f"**Type:** {item.issue_type}\n**Priority:** {item.priority}\n"
               f"**Status:** {item.status}\n\n**Description:**\n{item.description}\n{extra}")
    if item.labels:
        context += f"\n**Labels:** {', '.join(item.labels)}\n"
    if item.is_ephemeral:
        context += (
            "\n⚠️ **This is an internal/ephemeral work item that does NOT exist in the beads database.** "
            "Do NOT run any `bd` commands (bd show, bd close, bd update, etc.) for this item ID.\n"
        )
    return context


def _run_agent_with_ui(
    agent_id: str,
    agent_label: str,
    agent_type_key: str,
    cleanup_item: BeadsWorkItem,
    cleanup_prompt: str,
    cwd: str | None,
    parent_agent_id: str | None,
    work_item_id: str | None = None,
    work_item_title: str | None = None,
    modified_files: list[str] | None = None,
    timeout: float | None = None,
) -> tuple[bool, AgentStats | None]:
    """Invoke copilot with UI status tracking and metrics context."""
    try:
        from pokepoke.stats.metrics_context import agent_type_context
        with terminal_ui.ui.agent_output_for(agent_id), agent_type_context(agent_type_key):
            # Push agent status inside context so get_current_agent_type() returns the agent type
            terminal_ui.ui.push_agent_status(
                agent_id, agent_label, iteration=1, status="running",
                work_item_id=work_item_id, work_item_title=work_item_title,
                modified_files=modified_files,
                parent_agent_id=parent_agent_id,
                agent_type=agent_type_key,
                agent_prompt=cleanup_prompt,
            )
            copilot_result = invoke_copilot(cleanup_item, prompt=cleanup_prompt, cwd=cwd, timeout=timeout)

        status = "success" if copilot_result.success else "failed"
        terminal_ui.ui.push_agent_status(
            agent_id, agent_label, iteration=1, status=status,
            parent_agent_id=parent_agent_id,
            agent_type=agent_type_key,
        )

        return copilot_result.success, copilot_result.stats
    except Exception as e:
        logger.warning(f"Cleanup agent failed with error: {e}", exc_info=True)
        terminal_ui.ui.push_agent_status(
            agent_id, agent_label, iteration=1, status="failed",
            parent_agent_id=parent_agent_id,
            agent_type=agent_type_key,
        )
        raise


def _wait_for_merge_completion(agent_label: str, item_id: str) -> None:
    """Wait for an active merge operation to complete (polls every 30s, up to 10 min)."""
    logger.info(f"   ⏳ Merge operation in progress, waiting for completion before {agent_label}...")
    logger.info(f"{agent_label} agent for {item_id} waiting for merge completion")
    max_wait, interval, waited = 600, 30, 0

    while merge_lock_active() and waited < max_wait:
        time.sleep(interval)
        waited += interval
        logger.info(f"   ⏳ Still waiting for merge completion ({waited}s/{max_wait}s)...")

    if merge_lock_active():
        logger.warning("   ⚠️  Merge operation still active after 10 minutes, proceeding with caution")
        logger.warning(f"{agent_label} agent for {item_id} proceeding despite active merge lock")
    else:
        logger.info(f"   ✅ Merge operation completed, proceeding with {agent_label}")
        logger.info(f"{agent_label} agent for {item_id} proceeding after merge completion")


def invoke_cleanup_agent(
    item: BeadsWorkItem,
    cwd: str | None = None,
    modified_files: list[str] | None = None,
    parent_agent_id: str | None = None,
    wait_for_merge: bool = True
) -> tuple[bool, AgentStats | None]:
    """Invoke cleanup agent to commit uncommitted changes."""
    # Check if merge is active and wait if requested
    if wait_for_merge and merge_lock_active():
        _wait_for_merge_completion("cleanup", item.id)

    terminal_ui.ui.set_current_agent("Cleanup Agent")

    agent_id = f"{item.id}-cleanup"

    cleanup_prompt_template = load_prompt_file("cleanup.md")
    if cleanup_prompt_template is None:
        terminal_ui.ui.push_agent_status(
            agent_id, "Cleanup Agent", iteration=1, status="failed",
            parent_agent_id=parent_agent_id,
            agent_type="cleanup",
        )
        return False, None

    current_dir, current_branch, is_worktree = _get_current_git_context(cwd=cwd)
    cleanup_prompt_template = _apply_base_template_vars(
        cleanup_prompt_template, current_dir, current_branch, is_worktree,
    )

    work_item_context = _build_work_item_context(item, "Work Item Being Cleaned Up")
    cleanup_prompt = f"{work_item_context}\n\n---\n\n{cleanup_prompt_template}"

    cleanup_item = BeadsWorkItem(
        id=f"{item.id}-cleanup",
        title=f"Cleanup for {item.id}",
        description=cleanup_prompt,
        status=STATUS_IN_PROGRESS,
        priority=0,
        issue_type="task",
        labels=["cleanup", "automated"],
        is_ephemeral=True,
    )

    logger.info("\n🧹 Invoking cleanup agent...")

    return _run_agent_with_ui(
        agent_id, "Cleanup Agent", "cleanup",
        cleanup_item, cleanup_prompt, cwd, parent_agent_id,
        work_item_id=item.id, work_item_title=item.title,
        modified_files=modified_files,
        timeout=CLEANUP_AGENT_TIMEOUT,
    )


def invoke_merge_conflict_cleanup_agent(
    item: BeadsWorkItem,
    error_msg: str,
    unmerged_files: list[str] | None = None,
    cwd: str | None = None,
    parent_agent_id: str | None = None,
    wait_for_merge: bool = True
) -> tuple[bool, AgentStats | None]:
    """Invoke cleanup agent to resolve merge conflicts."""
    # Check if merge is active and wait if requested
    if wait_for_merge and merge_lock_active():
        _wait_for_merge_completion("conflict cleanup", item.id)

    terminal_ui.ui.set_current_agent("Merge Conflict Cleanup")

    agent_id = f"{item.id}-merge-fix"

    from pokepoke.git.merge_conflict import get_unmerged_files as git_get_unmerged
    from pokepoke.git.merge_conflict import is_merge_in_progress

    cleanup_prompt_template = load_prompt_file("merge-conflict-cleanup.md")
    if cleanup_prompt_template is None:
        logger.warning("⚠️ Falling back to standard cleanup agent")
        terminal_ui.ui.push_agent_status(
            agent_id, "Merge Conflict Cleanup", iteration=1, status="failed",
            parent_agent_id=parent_agent_id,
            agent_type="merge_conflict_cleanup",
        )
        return invoke_cleanup_agent(item, parent_agent_id=parent_agent_id, wait_for_merge=wait_for_merge)

    current_dir, current_branch, is_worktree = _get_current_git_context(cwd=cwd)

    is_merging = is_merge_in_progress()
    if unmerged_files is None:
        unmerged_files = git_get_unmerged()

    conflict_files_section = ""
    if unmerged_files:
        lines = [f"- `{f}`" for f in unmerged_files]
        conflict_files_section = "\n**Conflicted Files:**\n" + "\n".join(lines) + "\n"

    cleanup_prompt_template = _apply_base_template_vars(
        cleanup_prompt_template, current_dir, current_branch, is_worktree,
    )
    cleanup_prompt_template = cleanup_prompt_template.replace("{merge_error}", error_msg)
    cleanup_prompt_template = cleanup_prompt_template.replace("{worktree_path}", f"{WORKTREE_DIR}/{WORKTREE_TASK_PREFIX}{item.id}")
    cleanup_prompt_template = cleanup_prompt_template.replace("{is_merge_in_progress}", str(is_merging))
    cleanup_prompt_template = cleanup_prompt_template.replace("{conflict_files}", conflict_files_section)
    cleanup_prompt_template = cleanup_prompt_template.replace("{conflict_count}", str(len(unmerged_files)))

    merge_extra = f"""
**Merge State:**
- Merge in progress: {is_merging}
- Conflicted files: {len(unmerged_files)}
{conflict_files_section}

**Merge Error:**
{error_msg}
"""
    work_item_context = _build_work_item_context(item, "Work Item That Failed to Merge", extra=merge_extra)
    cleanup_prompt = f"{work_item_context}\n\n---\n\n{cleanup_prompt_template}"

    cleanup_item = BeadsWorkItem(
        id=f"{item.id}-merge-fix",
        title=f"Fix merge conflicts for {item.id}",
        description=cleanup_prompt,
        status=STATUS_IN_PROGRESS,
        priority=0,
        issue_type="task",
        labels=["cleanup", "merge-conflict"],
        is_ephemeral=True,
    )

    logger.info("\n🧹 Invoking merge conflict cleanup agent...")
    if unmerged_files:
        logger.info(f"   Conflicted files: {len(unmerged_files)}")
        for f in unmerged_files[:5]:
            logger.info(f"      - {f}")
        if len(unmerged_files) > 5:
            logger.info(f"      ... and {len(unmerged_files) - 5} more")

    return _run_agent_with_ui(
        agent_id, "Merge Conflict Cleanup", "merge_conflict_cleanup",
        cleanup_item, cleanup_prompt, cwd, parent_agent_id,
        work_item_id=item.id, work_item_title=item.title,
        modified_files=unmerged_files,
        timeout=CLEANUP_AGENT_TIMEOUT,
    )
