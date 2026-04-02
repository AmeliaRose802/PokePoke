"""Worker context management for retry continuity via beads comments.

When a worker fails (timeout, crash, gate rejection), structured context about
what was accomplished is saved as a beads comment. The next worker's prompt
includes these comments so it can pick up where the previous one left off.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

WORKER_CONTEXT_TAG = "[WORKER_CONTEXT]"
_MAX_CONTEXT_IN_PROMPT = 3


def save_worker_context(
    item_id: str,
    *,
    attempt_number: int,
    failure_reason: str,
    gate_feedback: list[str] | None = None,
    files_modified: list[str] | None = None,
    error_summary: str | None = None,
    add_comment_fn: Callable[[str, str], bool] | None = None,
) -> bool:
    """Serialize worker context as a beads comment for the next worker.

    Args:
        item_id: Beads item ID.
        attempt_number: Which attempt this was (1-based).
        failure_reason: Why the worker failed.
        gate_feedback: Recent gate-agent rejection feedback.
        files_modified: Files the worker touched.
        error_summary: Truncated error output.
        add_comment_fn: Optional override for the add_comment callable
            (used by orchestrator when a BeadsClient is available).

    Returns:
        True if the comment was persisted, False on error.
    """
    if add_comment_fn is None:
        from pokepoke.beads.beads_management import add_comment
        add_comment_fn = add_comment

    context: dict[str, Any] = {
        "attempt": attempt_number,
        "failure_reason": (failure_reason or "Unknown")[:500],
    }
    if gate_feedback:
        context["gate_feedback"] = [fb[:300] for fb in gate_feedback[-3:]]
    if files_modified:
        context["files_modified"] = files_modified[:20]
    if error_summary:
        context["error_summary"] = error_summary[:500]

    try:
        comment_text = f"{WORKER_CONTEXT_TAG} {json.dumps(context)}"
    except (TypeError, ValueError) as exc:
        logger.warning("Failed to serialize worker context for %s: %s", item_id, exc)
        return False

    return add_comment_fn(item_id, comment_text)


def get_worker_contexts(
    item_id: str,
    *,
    get_comments_fn: Callable[[str], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve previous worker context entries from beads comments.

    Args:
        item_id: Beads item ID.
        get_comments_fn: Optional override for fetching comments.

    Returns:
        List of parsed context dicts (most recent last), capped at
        ``_MAX_CONTEXT_IN_PROMPT``.
    """
    if get_comments_fn is None:
        from pokepoke.beads.beads_query import get_item_comments
        get_comments_fn = get_item_comments

    comments = get_comments_fn(item_id)
    contexts: list[dict[str, Any]] = []
    for comment in comments:
        text = comment.get("text", "") or comment.get("body", "") or ""
        if not text.startswith(WORKER_CONTEXT_TAG):
            continue
        json_str = text[len(WORKER_CONTEXT_TAG):].strip()
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                contexts.append(parsed)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Skipping malformed worker context comment on %s", item_id)
            continue

    return contexts[-_MAX_CONTEXT_IN_PROMPT:]


def format_worker_context_for_prompt(contexts: list[dict[str, Any]]) -> str | None:
    """Format worker context entries into a human-readable prompt section.

    Returns None if *contexts* is empty.
    """
    if not contexts:
        return None

    sections: list[str] = []
    for ctx in contexts:
        parts: list[str] = [f"**Attempt {ctx.get('attempt', '?')}:**"]
        if ctx.get("failure_reason"):
            parts.append(f"- Failure: {ctx['failure_reason']}")
        if ctx.get("gate_feedback"):
            parts.append("- Gate feedback:")
            parts.extend(f"  - {fb}" for fb in ctx["gate_feedback"])
        if ctx.get("files_modified"):
            parts.append(
                f"- Files previously modified: {', '.join(ctx['files_modified'])}"
            )
        if ctx.get("error_summary"):
            parts.append(f"- Error: {ctx['error_summary']}")
        sections.append("\n".join(parts))

    return "\n\n".join(sections)
