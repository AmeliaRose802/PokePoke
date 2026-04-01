"""Warm session service for creating and managing pre-warmed SDK sessions.

This module provides the async functionality to create warm sessions at startup
and refresh them when needed.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from pokepoke.config import get_config
from pokepoke.models.warm_session_pool import WarmSession, get_warm_session_pool
from pokepoke.prompts.prompts import PromptService

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _generate_warm_session_id(label: str) -> str:
    """Generate a unique session ID for a warm session."""
    timestamp = int(time.time())
    return f"warm-{label.lower()}-{timestamp}"


def _build_exploration_prompt(label: str, template_name: str) -> str:
    """Build the exploration prompt for warming a session.

    Args:
        label: The code area label to explore.
        template_name: Name of the prompt template.

    Returns:
        The rendered exploration prompt.
    """
    service = PromptService()
    variables = {"label": label}
    return service.load_and_render(template_name, variables)


async def warm_session_for_label(
    label: str,
    *,
    cwd: str | None = None,
    timeout: float = 120.0,
) -> WarmSession | None:
    """Create a warm session for a specific label.

    This runs a lightweight exploration prompt to prime the session with
    codebase context for the given label/code-area.

    Args:
        label: The label/code-area to warm (e.g., "orchestrator", "tests").
        cwd: Working directory for the session.
        timeout: Maximum time for the exploration phase.

    Returns:
        The created WarmSession, or None if warming failed.
    """
    pool = get_warm_session_pool()
    config = get_config()

    if not pool.enabled:
        logger.debug("Warm sessions disabled, skipping warm-up for '%s'", label)
        return None

    # Check if we should warm this label
    if not pool.mark_warming_in_progress(label):
        logger.debug("Warm-up already in progress for '%s', skipping", label)
        return None

    session_id = _generate_warm_session_id(label)
    logger.info(f"🔥 Warming session for label '{label}': {session_id}")

    try:
        # Build the exploration prompt
        prompt = _build_exploration_prompt(
            label,
            config.warm_sessions.exploration_prompt_template,
        )

        # Import here to avoid circular imports
        from pokepoke.models.copilot_sdk import invoke_copilot_sdk
        from pokepoke.types import BeadsWorkItem

        # Create a synthetic work item for the exploration
        exploration_item = BeadsWorkItem(
            id=f"warm-explore-{label}",
            title=f"Warm session exploration: {label}",
            status="in_progress",
            priority=0,
            issue_type="exploration",
            description=f"Pre-warming session for {label} code area",
            labels=[label],
            is_ephemeral=True,
        )

        # Run the exploration with deny_write to prevent modifications
        result = await invoke_copilot_sdk(
            work_item=exploration_item,
            prompt=prompt,
            timeout=timeout,
            deny_write=True,
            cwd=cwd,
            session_id=session_id,
        )

        if result.success:
            warm_session = pool.register_session(
                label=label,
                session_id=session_id,
                exploration_complete=True,
            )
            logger.info(
                f"✅ Warm session ready for '{label}': {session_id} "
                f"(tokens: {result.stats.input_tokens if result.stats else 0}+"
                f"{result.stats.output_tokens if result.stats else 0})"
            )
            return warm_session
        else:
            logger.warning(
                f"⚠️  Warm session exploration failed for '{label}': {result.error}"
            )
            pool.clear_warming_in_progress(label)
            return None

    except Exception as e:
        logger.error(f"❌ Failed to warm session for '{label}': {e}")
        pool.clear_warming_in_progress(label)
        return None


async def warm_up_pool(
    *,
    cwd: str | None = None,
    timeout_per_label: float = 120.0,
) -> dict[str, WarmSession | None]:
    """Warm up all configured labels in the pool.

    This is called at orchestrator startup to pre-create sessions.

    Args:
        cwd: Working directory for the sessions.
        timeout_per_label: Maximum time per label exploration.

    Returns:
        Dictionary mapping labels to their WarmSession (or None if failed).
    """
    pool = get_warm_session_pool()

    if not pool.enabled:
        logger.info("🔥 Warm sessions disabled, skipping pool warm-up")
        return {}

    labels_to_warm = pool.get_labels_needing_warmup()
    if not labels_to_warm:
        logger.info("🔥 All warm sessions are already valid")
        return {}

    logger.info(f"🔥 Warming up {len(labels_to_warm)} session(s): {', '.join(labels_to_warm)}")

    results: dict[str, WarmSession | None] = {}

    # Warm sessions sequentially to avoid overwhelming the SDK
    for label in labels_to_warm:
        try:
            session = await warm_session_for_label(
                label,
                cwd=cwd,
                timeout=timeout_per_label,
            )
            results[label] = session
        except Exception as e:
            logger.error(f"❌ Failed to warm session for '{label}': {e}")
            results[label] = None

    successful = sum(1 for s in results.values() if s is not None)
    logger.info(
        f"🔥 Warm-up complete: {successful}/{len(labels_to_warm)} sessions ready"
    )

    return results


def warm_up_pool_sync(
    *,
    cwd: str | None = None,
    timeout_per_label: float = 120.0,
) -> dict[str, WarmSession | None]:
    """Synchronous wrapper for warm_up_pool."""
    return asyncio.run(warm_up_pool(cwd=cwd, timeout_per_label=timeout_per_label))


def refresh_pool_after_merge(*, cwd: str | None = None) -> None:
    """Refresh warm sessions after a merge changes the codebase.

    This invalidates all existing sessions and optionally re-warms them.
    Called after successful merges to main branch.

    Args:
        cwd: Working directory for re-warming.
    """
    pool = get_warm_session_pool()
    config = get_config()

    if not pool.enabled:
        return

    if not config.warm_sessions.refresh_on_merge:
        logger.debug("refresh_on_merge disabled, skipping post-merge refresh")
        return

    invalidated = pool.invalidate_all()
    if invalidated > 0:
        logger.info(
            f"🔄 Invalidated {invalidated} warm session(s) after merge; "
            f"will re-warm on next startup or dispatch"
        )


def get_warm_session_stats() -> dict[str, int | dict[str, int]]:
    """Get statistics about the warm session pool."""
    return get_warm_session_pool().get_stats()
