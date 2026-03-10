"""Handoff context builder for gate agent verification.

Captures structured information about work-agent changes (changed files,
diff stats, commit history, unified diff) so the gate agent can skip
re-discovering the project structure and reviewing diffs via git commands.
"""

import logging
import subprocess

from .git_operations import get_default_branch

logger = logging.getLogger(__name__)

# Truncate unified diff content beyond this limit to avoid token explosion.
_MAX_DIFF_CHARS = 20_000


def build_handoff_context(cwd: str | None = None) -> str:
    """Build a structured context handoff summary for the gate agent.

    Captures the list of changed files (name + status), a compact diff stat,
    recent commit messages, and the full unified diff relative to the merge
    base with the default branch.  Returns an empty string if nothing useful
    can be gathered (e.g. no commits ahead).

    The output is plain-text Markdown suitable for injection into the
    gate-agent prompt so it can skip re-discovering the project structure
    and avoid running redundant ``git diff`` / ``git log`` commands.
    """
    target_branch = get_default_branch()

    # 1. Changed files with status (A/M/D/R)
    try:
        name_status = subprocess.run(
            ["git", "diff", "--name-status", f"{target_branch}...HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors='replace',
            timeout=15, cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("git diff --name-status failed: %s", exc)
        name_status = None

    changed_files: list[str] = []
    if name_status and name_status.returncode == 0 and name_status.stdout.strip():
        changed_files = [
            line for line in name_status.stdout.strip().splitlines()
            if line.strip()
        ]

    if not changed_files:
        return ""

    # 2. Diff stat (compact size summary)
    try:
        diff_stat = subprocess.run(
            ["git", "diff", "--stat", f"{target_branch}...HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors='replace',
            timeout=15, cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("git diff --stat failed: %s", exc)
        diff_stat = None

    stat_text = ""
    if diff_stat and diff_stat.returncode == 0 and diff_stat.stdout.strip():
        stat_text = diff_stat.stdout.strip()

    # 3. Recent commit messages (one-line summaries)
    try:
        log_result = subprocess.run(
            ["git", "log", "--oneline", f"{target_branch}..HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors='replace',
            timeout=10, cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("git log --oneline failed: %s", exc)
        log_result = None

    commit_lines: list[str] = []
    if log_result and log_result.returncode == 0 and log_result.stdout.strip():
        commit_lines = [
            line for line in log_result.stdout.strip().splitlines()
            if line.strip()
        ]

    # 4. Unified diff content (actual code changes)
    try:
        diff_result = subprocess.run(
            ["git", "diff", f"{target_branch}...HEAD"],
            capture_output=True, text=True, encoding="utf-8",
            errors='replace',
            timeout=30, cwd=cwd,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.debug("git diff failed: %s", exc)
        diff_result = None

    diff_content = ""
    diff_truncated = False
    if diff_result and diff_result.returncode == 0 and diff_result.stdout.strip():
        raw = diff_result.stdout.strip()
        if len(raw) > _MAX_DIFF_CHARS:
            diff_content = raw[:_MAX_DIFF_CHARS]
            diff_truncated = True
        else:
            diff_content = raw

    # 5. Assemble structured handoff block
    sections: list[str] = []
    sections.append("## Work Agent Handoff Context")
    sections.append("")
    sections.append("The following information was captured from the work agent's session.")
    sections.append("Use this to skip re-discovering the project — focus your verification on these files.")
    sections.append("")

    sections.append("### Changed Files")
    sections.append("```")
    sections.extend(changed_files)
    sections.append("```")

    if stat_text:
        sections.append("")
        sections.append("### Diff Summary")
        sections.append("```")
        sections.append(stat_text)
        sections.append("```")

    if commit_lines:
        sections.append("")
        sections.append("### Commit History")
        sections.append("```")
        sections.extend(commit_lines)
        sections.append("```")

    if diff_content:
        sections.append("")
        sections.append("### Diff Content")
        sections.append("```diff")
        sections.append(diff_content)
        sections.append("```")
        if diff_truncated:
            sections.append("*(diff truncated — run `git diff` for the full output)*")

    sections.append("")
    sections.append("**Start your verification by reviewing the diff content above rather than running git commands.**")

    return "\n".join(sections)
