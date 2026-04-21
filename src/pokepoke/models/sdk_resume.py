"""Resume prompt helpers for the Copilot SDK integration."""
from collections.abc import Sequence

from pokepoke.types import BeadsWorkItem

_MAX_OUTPUT_SUMMARY_LEN = 2000


def _summarize_output(
    output_lines: Sequence[str], max_length: int = _MAX_OUTPUT_SUMMARY_LEN,
) -> str | None:
    """Extract a truncated summary from agent output lines.

    Keeps the most recent output (tail), which represents the agent's
    latest progress and is most useful for resume context.
    Returns ``None`` if there is no meaningful output.
    """
    text = "".join(output_lines).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return "...(earlier output truncated)...\n" + text[-max_length:]


def build_gate_resume_prompt(
    work_item: BeadsWorkItem,
    handoff_context: str | None = None,
    previous_output_summary: str | None = None,
    default_branch: str = "master",
) -> str:
    """Build a prompt for resuming a timed-out gate agent session."""
    lines = [
        f"## Gate Agent Session Resume - {work_item.id}: {work_item.title}",
        "",
        "Your previous **gate verification session timed out** before",
        "reaching a verdict.  You are being resumed in the same SDK session",
        "so your earlier tool results and reasoning should still be available.",
        "",
        "**Continue your verification from where you left off.**",
        "",
        f"**Item:** {work_item.id} - {work_item.title}",
        f"**Type:** {work_item.issue_type} | **Priority:** {work_item.priority}",
    ]
    if work_item.description:
        lines.extend(["", "**Description:**", work_item.description])
    if handoff_context:
        lines.extend(["", "### Handoff Context", "", handoff_context])
    if previous_output_summary:
        lines.extend(["", "### Previous Progress", "",
                       "Here is the tail of your previous gate session output:",
                       "", "```", previous_output_summary, "```"])
    lines.extend([
        "", "### Your Task", "",
        "You are the **Gate Agent** - a read-only verification agent.",
        f"Review the changes on this branch compared to `{default_branch}`.",
        "Run tests, check code quality, and verify the implementation.",
        "", "Respond with a JSON verdict:",
        '```json', '{{"status": "success", "message": "...", "reason": "..."}}', '```',
        "or", '```json', '{{"status": "failure", "reason": "...", "details": "..."}}', '```',
    ])
    return "\n".join(lines)


def build_gate_reverify_prompt(
    work_item: BeadsWorkItem,
    handoff_context: str | None = None,
    previous_output_summary: str | None = None,
    previous_rejection: str | None = None,
    default_branch: str = "master",
) -> str:
    """Build a prompt for resuming a gate session after a rejected review.

    The resumed session should focus on whether the work agent addressed the
    prior gate feedback instead of re-reviewing the entire change set from
    scratch.
    """
    lines = [
        f"## Gate Agent Reverification Resume - {work_item.id}: {work_item.title}",
        "",
        "Your previous gate verification session rejected this work.",
        "The work agent has now addressed that feedback.",
        "Resume the same SDK session and focus on re-verifying the specific issues you raised.",
        "",
        f"**Item:** {work_item.id} - {work_item.title}",
        f"**Type:** {work_item.issue_type} | **Priority:** {work_item.priority}",
    ]
    if work_item.description:
        lines.extend(["", "**Description:**", work_item.description])
    if handoff_context:
        lines.extend(["", "### Handoff Context", "", handoff_context])
    if previous_rejection:
        lines.extend(["", "### Previous Gate Feedback", "", previous_rejection])
    if previous_output_summary:
        lines.extend([
            "", "### Previous Progress", "",
            "Here is the tail of your previous gate session output:",
            "", "```", previous_output_summary, "```",
        ])
    lines.extend([
        "", "### Your Task", "",
        "You are the **Gate Agent** - a read-only verification agent.",
        f"Review the changes on this branch compared to `{default_branch}`.",
        "Confirm whether the work agent fixed the issues you previously rejected.",
        "Do not re-explain the whole change set; focus on the repaired items and any regressions.",
        "", "Respond with a JSON verdict:",
        '```json', '{{"status": "success", "message": "...", "reason": "..."}}', '```',
        "or", '```json', '{{"status": "failure", "reason": "...", "details": "..."}}', '```',
    ])
    return "\n".join(lines)


def build_resume_prompt(
    work_item: BeadsWorkItem,
    previous_output_summary: str | None = None,
    retry_feedback: list[str] | None = None,
) -> str:
    """Build a prompt for resuming a timed-out session."""
    lines = [
        f"## Session Resume - {work_item.id}: {work_item.title}",
        "",
        "Your previous session **timed out** before completing the task.",
        "You are being resumed in the same SDK session so your earlier",
        "tool results, file reads, and reasoning should still be available.",
        "",
        "**Continue from where you left off and complete the task.**",
        "",
        f"**Item:** {work_item.id} - {work_item.title}",
        f"**Type:** {work_item.issue_type} | **Priority:** {work_item.priority}",
    ]
    if work_item.description:
        lines.extend(["", "**Description:**", work_item.description])
    if previous_output_summary:
        lines.extend(["", "### Previous Progress", "",
                       "Here is the tail of your previous session output for context:",
                       "", "```", previous_output_summary, "```"])
    if retry_feedback:
        lines.extend(["", "### Feedback from Previous Attempts", ""])
        lines.extend(f"- {fb}" for fb in retry_feedback)
    lines.extend([
        "", "**Success Criteria:**",
        "- Provided item is fully implemented",
        "- All pre-commit validation passes successfully",
        "- All changes are committed and the worktree has been merged",
    ])
    return "\n".join(lines)
