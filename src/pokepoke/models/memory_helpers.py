"""Memory integration helpers for agent workflows."""
import logging
from pathlib import Path

from pokepoke.config import get_config
from pokepoke.models.mcp_memory_client import MCPMemoryClient, MemoryEntity
from pokepoke.types import BeadsWorkItem

logger = logging.getLogger(__name__)


def get_memory_client(repo_root: Path | None = None) -> MCPMemoryClient | None:
    """Get MCP memory client if enabled in config.

    Args:
        repo_root: Optional repository root path

    Returns:
        MCPMemoryClient instance if memory is enabled, None otherwise
    """
    config = get_config()

    if not config.mcp_server.memory_enabled:
        return None

    try:
        memory_file = config.mcp_server.memory_file_path
        return MCPMemoryClient(memory_file_path=memory_file, repo_root=repo_root)
    except Exception as e:
        logger.warning(f"Failed to initialize memory client: {e}")
        return None


def retrieve_relevant_memories(work_item: BeadsWorkItem, repo_root: Path | None = None) -> str | None:
    """Retrieve memories relevant to a work item.

    Args:
        work_item: Work item to retrieve memories for
        repo_root: Optional repository root path

    Returns:
        Formatted memory context string or None if no memories found
    """
    client = get_memory_client(repo_root)
    if not client:
        return None

    try:
        # Build search queries from work item context
        queries = []

        # Search by labels
        if work_item.labels:
            queries.extend(work_item.labels)

        # Search by issue type
        if work_item.issue_type:
            queries.append(work_item.issue_type)

        # Search by title keywords
        if work_item.title:
            # Extract meaningful keywords (skip common words)
            skip_words = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
            title_words = work_item.title.lower().split()
            keywords = [w for w in title_words if len(w) > 3 and w not in skip_words]
            queries.extend(keywords[:3])  # Top 3 keywords

        # Retrieve memories for each query
        all_memories: dict[str, MemoryEntity] = {}
        for query in queries:
            memories = client.retrieve_facts(query)
            for memory in memories:
                # Deduplicate by entity name
                all_memories[memory.name] = memory

        if not all_memories:
            logger.debug(f"No relevant memories found for item {work_item.id}")
            return None

        # Format memories as context
        lines = ["## Relevant Knowledge from Previous Sessions\n"]
        lines.append("The following facts were discovered in previous work sessions:\n")

        for entity in all_memories.values():
            lines.append(f"\n### {entity.name} ({entity.entity_type})")
            for obs in entity.observations:
                # Remove timestamp prefix for display
                if obs.startswith("[") and "]" in obs:
                    obs_text = obs[obs.index("]") + 2:]
                else:
                    obs_text = obs
                lines.append(f"- {obs_text}")

        lines.append("\nUse this knowledge to work more efficiently.")

        memory_context = "\n".join(lines)
        logger.info(f"Retrieved {len(all_memories)} relevant memories for item {work_item.id}")
        return memory_context

    except Exception as e:
        logger.error(f"Failed to retrieve memories: {e}")
        return None


def store_agent_discoveries(
    work_item: BeadsWorkItem,
    discoveries: dict[str, dict[str, str | list[str]]],
    repo_root: Path | None = None
) -> bool:
    """Store agent discoveries in memory.

    Args:
        work_item: Work item that was processed
        discoveries: Dict mapping entity names to {entity_type, observations}
                    Example: {
                        "workflow.py": {
                            "entity_type": "file",
                            "observations": ["Main orchestration loop", "Handles work item selection"]
                        }
                    }
        repo_root: Optional repository root path

    Returns:
        True if successful, False otherwise
    """
    client = get_memory_client(repo_root)
    if not client:
        return False

    try:
        success_count = 0
        for entity_name, entity_data in discoveries.items():
            entity_type_value = entity_data.get("entity_type", "unknown")
            if not isinstance(entity_type_value, str):
                continue
            entity_type = entity_type_value

            observations_value = entity_data.get("observations", [])
            if not isinstance(observations_value, list):
                continue
            observations = observations_value

            if not observations:
                continue

            if client.store_fact(entity_name, entity_type, observations):
                success_count += 1

        logger.info(f"Stored {success_count}/{len(discoveries)} discoveries in memory")

        # Run decay cleanup if configured
        config = get_config()
        if config.mcp_server.confidence_decay_days > 0:
            removed = client.clean_stale_observations(config.mcp_server.confidence_decay_days)
            if removed > 0:
                logger.debug(f"Cleaned {removed} stale observations during storage")

        return success_count > 0

    except Exception as e:
        logger.error(f"Failed to store discoveries: {e}")
        return False


def auto_discover_from_prompt(work_prompt: str, work_item: BeadsWorkItem) -> dict[str, dict[str, str | list[str]]]:
    """Extract discoverable facts from work prompt for auto-storage.

    This is a simple heuristic-based discovery that can be called after work completion
    to automatically extract and store learned facts.

    Args:
        work_prompt: The prompt sent to the agent
        work_item: The work item being processed

    Returns:
        Dictionary of discoveries in format expected by store_agent_discoveries
    """
    discoveries: dict[str, dict[str, str | list[str]]] = {}

    # Auto-discover from work item labels
    if work_item.labels:
        for label in work_item.labels:
            entity_name = f"label::{label}"
            observations: list[str] = [
                f"Work item {work_item.id} had this label",
                f"Issue type: {work_item.issue_type}"
            ]

            discoveries[entity_name] = {
                "entity_type": "label",
                "observations": observations
            }

    # Auto-discover work item type patterns
    if work_item.issue_type:
        entity_name = f"issue_type::{work_item.issue_type}"
        pattern_observations: list[str] = [
            f"Work item {work_item.id} was of this type",
            f"Labels: {', '.join(work_item.labels) if work_item.labels else 'none'}"
        ]

        discoveries[entity_name] = {
            "entity_type": "pattern",
            "observations": pattern_observations
        }

    return discoveries
