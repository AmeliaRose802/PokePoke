"""Decomposition agent — breaks failing work items into SDK-analysed sub-tasks.

Creates children with blocking deps (serial execution), label propagation,
title validation, and dedup checking.
"""

import json
import logging
import re
import subprocess
from dataclasses import dataclass

from pokepoke.beads.beads_query import _parse_beads_json, _run_bd
from pokepoke.types import BeadsWorkItem

logger = logging.getLogger(__name__)

DECOMPOSITION_LABEL = "auto-decomposed"
DECOMPOSITION_COMMENT_PREFIX = "🔀 Auto-decomposition triggered"

MIN_TITLE_LENGTH = 10
_PLACEHOLDER_TITLE_RE = re.compile(
    r"^(desc|test desc|description|title|sub-?task \d+|implement|add tests|"
    r"implement core logic|add tests and validation|todo|fixme|tbd|n/?a)$",
    re.IGNORECASE,
)

_DECOMPOSITION_TIMEOUT = 120.0


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


def _is_valid_title(title: str) -> bool:
    """Return True if *title* looks like a meaningful subtask name."""
    stripped = title.strip()
    return len(stripped) >= MIN_TITLE_LENGTH and not _PLACEHOLDER_TITLE_RE.match(stripped)


def _build_decomposition_prompt(item: BeadsWorkItem) -> str:
    """Build the prompt for the Copilot SDK decomposition invocation."""
    from pokepoke.prompts.prompts import PromptService
    from pokepoke.utils.prompt_sanitizer import sanitize_prompt_input, sanitize_short

    service = PromptService()
    variables = {
        "item_id": item.id,
        "title": sanitize_short(item.title, "title"),
        "description": sanitize_prompt_input(
            item.description, field_name="description",
        ),
        "issue_type": sanitize_short(item.issue_type, "issue_type"),
        "priority": item.priority,
        "labels": sanitize_short(
            ", ".join(item.labels) if item.labels else None, "labels",
        ),
    }
    return service.load_and_render("decomposition", variables)


def _parse_subtasks_from_output(output: str, default_priority: int) -> list[SubTask]:
    """Parse a JSON array of {title, description} from SDK output."""
    # Try to find a JSON array (possibly inside a fenced code block)
    match = re.search(r'\[.*?\]', output, re.DOTALL)
    if not match:
        return []

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    subtasks: list[SubTask] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip()[:80]
        description = str(entry.get("description", "")).strip()
        if not _is_valid_title(title):
            logger.info("🔀 Rejected subtask with invalid title: '%s'", title)
            continue
        subtasks.append(SubTask(
            title=title,
            description=description,
            priority=default_priority,
        ))
    return subtasks


def _invoke_sdk_for_decomposition(item: BeadsWorkItem) -> list[SubTask]:
    """Invoke the Copilot SDK to decompose *item* into subtasks."""
    from pokepoke.models.ai_backends import invoke_copilot

    prompt = _build_decomposition_prompt(item)

    result = invoke_copilot(
        work_item=item,
        prompt=prompt,
        timeout=_DECOMPOSITION_TIMEOUT,
        deny_write=True,
    )

    if not result.success or not result.output:
        logger.warning(
            "🔀 SDK decomposition failed for %s: %s",
            item.id,
            result.error or "no output",
        )
        return []

    return _parse_subtasks_from_output(result.output, item.priority)


def _get_existing_child_titles(parent_id: str) -> set[str]:
    """Return lowercased titles of existing children of *parent_id*."""
    try:
        from pokepoke.beads.beads_hierarchy import get_children
        children = get_children(parent_id)
        return {c.title.lower().strip() for c in children if c.title}
    except Exception as exc:
        logger.debug("Could not fetch existing children for %s: %s", parent_id, exc)
        return set()


def _create_child_item(
    subtask: SubTask,
    parent_id: str,
    extra_labels: list[str] | None = None,
) -> str | None:
    """Create a beads child item linked to *parent_id*. Returns ID or None."""
    all_labels = [DECOMPOSITION_LABEL]
    if extra_labels:
        for lbl in extra_labels:
            if lbl not in all_labels:
                all_labels.append(lbl)

    cmd = [
        "create",
        subtask.title,
        "--type", subtask.issue_type,
        "--priority", str(subtask.priority),
        "--description", subtask.description,
        "--deps", f"parent:{parent_id}",
        "--labels", ",".join(all_labels),
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


def _update_parent_metadata(parent_id: str, child_ids: list[str]) -> bool:
    """Mark parent with decomposition metadata and ``auto-decomposed`` label."""
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
        labels = item.get("labels") or []
        if not isinstance(labels, list):
            labels = []

        metadata["decomposed"] = True
        metadata["decomposition_child_ids"] = child_ids

        cmd = [
            "update", parent_id,
            "--metadata", json.dumps(metadata),
        ]
        if DECOMPOSITION_LABEL not in labels:
            cmd.extend(["--add-label", DECOMPOSITION_LABEL])
        _run_bd(cmd)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, Exception) as e:
        logger.warning("Failed to update parent metadata for %s: %s", parent_id, e)
        return False


def _add_blocking_dependency(blocker_id: str, blocked_id: str) -> bool:
    """Add a ``blocks`` dep so *blocked_id* waits for *blocker_id*."""
    try:
        _run_bd([
            "update", blocked_id,
            "--deps", f"blocks:{blocker_id}",
        ], check=False, timeout=15)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning(
            "Failed to add blocking dep %s → %s: %s",
            blocker_id, blocked_id, exc,
        )
        return False


def run_decomposition(item: BeadsWorkItem, failure_count: int) -> DecompositionResult:
    """Decompose a failing item via SDK analysis, creating serialised child tasks."""
    logger.info(
        "\n🔀 Decomposition Agent: item %s failed %d times — breaking into sub-tasks",
        item.id, failure_count,
    )

    subtasks = _invoke_sdk_for_decomposition(item)
    if not subtasks:
        reason = "SDK decomposition produced no valid subtasks"
        logger.warning("🔀 Decomposition skipped for %s: %s", item.id, reason)
        return DecompositionResult(
            success=False, parent_id=item.id, child_ids=[], reason=reason,
        )

    # Dedup: drop subtasks whose title already exists as a child.
    existing_titles = _get_existing_child_titles(item.id)
    if existing_titles:
        before = len(subtasks)
        subtasks = [
            s for s in subtasks
            if s.title.lower().strip() not in existing_titles
        ]
        dropped = before - len(subtasks)
        if dropped:
            logger.info(
                "🔀 Dropped %d duplicate subtask(s) for %s", dropped, item.id,
            )
    if not subtasks:
        reason = "All proposed subtasks already exist as children"
        logger.info("🔀 Decomposition skipped for %s: %s", item.id, reason)
        return DecompositionResult(
            success=False, parent_id=item.id, child_ids=[], reason=reason,
        )

    # Labels to propagate from parent (excluding the decomposition label itself)
    parent_labels = [
        lbl for lbl in (item.labels or [])
        if lbl != DECOMPOSITION_LABEL
    ]

    logger.info("🔀 Creating %d sub-tasks for %s", len(subtasks), item.id)

    child_ids: list[str] = []
    prev_child_id: str | None = None
    for subtask in subtasks:
        child_id = _create_child_item(
            subtask,
            parent_id=item.id,
            extra_labels=parent_labels,
        )
        if child_id:
            # Add blocking relationship: previous sibling blocks this one
            if prev_child_id:
                _add_blocking_dependency(prev_child_id, child_id)
            child_ids.append(child_id)
            prev_child_id = child_id
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
    item: BeadsWorkItem, failure_count: int, threshold: int, enabled: bool = True,
) -> bool:
    """Return True if *item* should be decomposed based on failure count."""
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
