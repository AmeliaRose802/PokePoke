"""Decomposition agent - breaks repeatedly failing work items into sub-tasks.

When a work item fails multiple consecutive retry cycles, the decomposition
agent analyzes the item and creates smaller child tasks in beads linked via
parent-child dependencies.  This avoids wasting compute on items that are
too large or complex for a single agent pass.
"""

import json
import logging
import subprocess
from dataclasses import dataclass

from pokepoke.beads.beads_query import _parse_beads_json, _run_bd
from pokepoke.types import BeadsWorkItem

logger = logging.getLogger(__name__)

DECOMPOSITION_LABEL = "auto-decomposed"
DECOMPOSITION_COMMENT_PREFIX = "🔀 Auto-decomposition triggered"


@dataclass
class SubTask:
    """A sub-task to be created as a beads child item."""

    title: str
    description: str
    priority: int
    issue_type: str = "task"


@dataclass
class DecompositionResult:
    """Result of running the decomposition agent."""

    success: bool
    parent_id: str
    child_ids: list[str]
    reason: str


def _build_subtasks_from_item(item: BeadsWorkItem) -> list[SubTask]:
    """Analyze a work item and produce a list of sub-tasks.

    Uses simple heuristic decomposition based on the item's description.
    Each logical section or requirement in the description becomes a sub-task.
    """
    description = item.description or ""
    title = item.title or ""

    # Split description into logical chunks by looking for common patterns:
    # numbered lists, bullet points, section headers, or blank-line-separated blocks
    lines = description.strip().splitlines()
    chunks: list[list[str]] = []
    current_chunk: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Detect list items or section breaks
        is_new_item = (
            stripped.startswith(("- ", "* ", "• "))
            or (len(stripped) >= 2 and stripped[0].isdigit() and stripped[1] in ".)")
            or stripped.startswith(("## ", "### "))
        )
        if is_new_item and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [stripped]
        elif not stripped and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
        elif stripped:
            current_chunk.append(stripped)

    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        # If no structure found, create two generic sub-tasks
        return [
            SubTask(
                title=f"Implement core logic: {title}",
                description=f"Implement the core functionality for: {title}\n\n{description}",
                priority=item.priority,
            ),
            SubTask(
                title=f"Add tests and validation: {title}",
                description=f"Write tests and validation for: {title}",
                priority=item.priority,
            ),
        ]

    subtasks: list[SubTask] = []
    for i, chunk in enumerate(chunks, 1):
        chunk_text = "\n".join(chunk)
        # Clean up bullet/number prefixes for the title
        first_line = chunk[0]
        for prefix in ("- ", "* ", "• ", "## ", "### "):
            if first_line.startswith(prefix):
                first_line = first_line[len(prefix):]
                break
        if len(first_line) >= 2 and first_line[0].isdigit() and first_line[1] in ".)":
            first_line = first_line[2:].strip()

        # Truncate title to reasonable length
        sub_title = first_line[:80].strip() or f"Sub-task {i} of: {title}"

        subtasks.append(SubTask(
            title=sub_title,
            description=f"Part of: {title}\n\n{chunk_text}",
            priority=item.priority,
        ))

    return subtasks


def _create_child_item(
    subtask: SubTask,
    parent_id: str,
) -> str | None:
    """Create a single beads child item linked to a parent.

    Returns the created item's ID, or None on failure.
    """
    cmd = [
        "create",
        subtask.title,
        "--type", subtask.issue_type,
        "--priority", str(subtask.priority),
        "--description", subtask.description,
        "--deps", f"parent:{parent_id}",
        "--labels", DECOMPOSITION_LABEL,
        "--json",
    ]

    try:
        result = _run_bd(cmd, check=False, timeout=30)
        if result.returncode != 0:
            logger.warning(
                "Failed to create child item '%s': %s",
                subtask.title,
                result.stderr.strip() if result.stderr else f"exit code {result.returncode}",
            )
            return None

        data = _parse_beads_json(result.stdout)
        if isinstance(data, dict):
            item_id: str | None = data.get("id")
            return item_id
        if isinstance(data, list) and data:
            first: str | None = data[0].get("id")
            return first
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Timed out creating child item: %s", subtask.title)
        return None
    except subprocess.CalledProcessError as e:
        logger.warning("Failed to create child item '%s': %s", subtask.title, e.stderr)
        return None


def _update_parent_metadata(
    parent_id: str,
    child_ids: list[str],
) -> bool:
    """Update the parent item's metadata to record decomposition.

    Marks the parent with decomposition metadata and adds the
    ``auto-decomposed`` label so the orchestrator can skip it in future runs.
    """
    try:
        # Read current metadata
        result = _run_bd(["show", parent_id, "--json"], check=False)
        data = _parse_beads_json(result.stdout)
        if data is None:
            return False

        item = data[0] if isinstance(data, list) else data
        metadata = item.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        metadata["decomposed"] = True
        metadata["decomposition_child_ids"] = child_ids

        _run_bd([
            "update", parent_id,
            "--metadata", json.dumps(metadata),
            "--labels", DECOMPOSITION_LABEL,
        ])
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, Exception) as e:
        logger.warning("Failed to update parent metadata for %s: %s", parent_id, e)
        return False


def run_decomposition(
    item: BeadsWorkItem,
    failure_count: int,
) -> DecompositionResult:
    """Decompose a repeatedly failing work item into smaller sub-tasks.

    Analyzes the work item, generates sub-tasks, creates them as beads
    child items linked to the parent, and updates the parent metadata.

    Args:
        item: The work item that has repeatedly failed.
        failure_count: Number of consecutive failures that triggered decomposition.

    Returns:
        DecompositionResult with created child IDs and outcome.
    """
    logger.info(
        "\n🔀 Decomposition Agent: item %s failed %d times — breaking into sub-tasks",
        item.id, failure_count,
    )

    subtasks = _build_subtasks_from_item(item)
    if not subtasks:
        reason = "Could not determine sub-tasks from item description"
        logger.warning("🔀 Decomposition skipped for %s: %s", item.id, reason)
        return DecompositionResult(
            success=False, parent_id=item.id, child_ids=[], reason=reason,
        )

    logger.info("🔀 Creating %d sub-tasks for %s", len(subtasks), item.id)

    child_ids: list[str] = []
    for subtask in subtasks:
        child_id = _create_child_item(subtask, parent_id=item.id)
        if child_id:
            child_ids.append(child_id)
            logger.info("   ✅ Created child: %s — %s", child_id, subtask.title)
        else:
            logger.warning("   ❌ Failed to create child: %s", subtask.title)

    if not child_ids:
        reason = "Failed to create any child items in beads"
        logger.error("🔀 Decomposition failed for %s: %s", item.id, reason)
        return DecompositionResult(
            success=False, parent_id=item.id, child_ids=[], reason=reason,
        )

    _update_parent_metadata(item.id, child_ids)

    # Add a comment to the parent item documenting the decomposition
    from pokepoke.beads.beads_management import add_comment
    add_comment(
        item.id,
        f"{DECOMPOSITION_COMMENT_PREFIX} after {failure_count} consecutive failures.\n"
        f"Created {len(child_ids)} sub-tasks: {', '.join(child_ids)}",
    )

    reason = f"Created {len(child_ids)}/{len(subtasks)} sub-tasks"
    logger.info("🔀 Decomposition complete for %s: %s", item.id, reason)
    return DecompositionResult(
        success=True, parent_id=item.id, child_ids=child_ids, reason=reason,
    )


def should_decompose(
    item: BeadsWorkItem,
    failure_count: int,
    threshold: int,
    enabled: bool = True,
) -> bool:
    """Check whether a work item should be decomposed.

    Args:
        item: The work item to check.
        failure_count: Number of consecutive failures.
        threshold: Minimum failures before decomposition triggers.
        enabled: Whether decomposition is enabled in config.

    Returns:
        True if decomposition should be triggered.
    """
    if not enabled:
        return False

    if failure_count < threshold:
        return False

    # Don't decompose items that were already decomposed
    if item.labels and DECOMPOSITION_LABEL in item.labels:
        logger.info(
            "🔀 Skipping decomposition for %s — already decomposed", item.id,
        )
        return False

    return True
