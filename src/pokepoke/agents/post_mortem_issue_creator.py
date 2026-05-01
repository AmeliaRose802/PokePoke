"""Post-mortem beads issue creation and deduplication."""

import json
import logging
from typing import Any

from pokepoke.agents.post_mortem_analyzer import FailurePattern
from pokepoke.beads.beads_query import _run_bd
from pokepoke.utils.constants import BEADS_BINARY_BD

logger = logging.getLogger(__name__)


class BeadsIssueCreator:
    """Creates beads items for post-mortem failure patterns with deduplication."""

    POST_MORTEM_LABEL = "post-mortem"
    AUTO_FILED_LABEL = "auto-filed"

    def __init__(self, beads_backend: str = BEADS_BINARY_BD):
        """Initialize the issue creator."""
        self.beads_backend = beads_backend

    def file_issues(self, patterns: list[FailurePattern]) -> list[str]:
        """File beads items for failure patterns, with deduplication."""
        if not patterns:
            logger.info("No patterns to file")
            return []

        # Get existing post-mortem items to check for duplicates
        existing_items = self._get_existing_post_mortem_items()

        created_ids = []
        for pattern in patterns:
            # Check if similar issue already exists
            if self._is_duplicate(pattern, existing_items):
                logger.info(f"Skipping duplicate pattern: {pattern.pattern_type}")
                continue

            # Create the issue
            item_id = self._create_beads_item(pattern)
            if item_id:
                created_ids.append(item_id)
                logger.info(f"Created beads item {item_id} for pattern: {pattern.pattern_type}")
            else:
                logger.warning(f"Failed to create item for pattern: {pattern.pattern_type}")

        return created_ids

    def _get_existing_post_mortem_items(self) -> list[dict[str, Any]]:
        """Get all existing post-mortem labeled items."""
        try:
            # Query beads for items with post-mortem label
            result = _run_bd(
                ["list", "--label", self.POST_MORTEM_LABEL, "--json"],
                check=False,
                timeout=30,
            )

            if result.returncode != 0:
                logger.warning(f"Failed to query existing post-mortem items: {result.stderr}")
                return []

            # Parse JSON output
            try:
                output = result.stdout.strip()
                if not output:
                    return []

                # Filter out warning/note lines
                lines = [line for line in output.split('\n')
                        if line.strip() and not line.startswith(('Note:', 'Warning:', 'Hint:'))]
                filtered_output = '\n'.join(lines)

                if not filtered_output:
                    return []

                items = json.loads(filtered_output)
                return items if isinstance(items, list) else []
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse beads JSON output: {e}")
                return []

        except Exception as e:
            logger.warning(f"Error querying existing post-mortem items: {e}")
            return []

    def _is_duplicate(self, pattern: FailurePattern, existing_items: list[dict[str, Any]]) -> bool:
        """Check if a similar pattern already exists."""
        if not existing_items:
            return False

        # Check for similar titles or pattern types
        for item in existing_items:
            # Skip closed items
            if item.get("status") == "closed":
                continue

            title = item.get("title", "")
            description = item.get("description", "")

            # Check if pattern type matches in title
            if pattern.pattern_type in title.lower():
                logger.debug(f"Found potential duplicate by pattern type: {item.get('id')}")
                return True

            # Check for similar affected items (>50% overlap)
            if pattern.affected_items and description:
                affected_in_desc = [item_id for item_id in pattern.affected_items
                                   if item_id in description]
                if len(affected_in_desc) > len(pattern.affected_items) * 0.5:
                    logger.debug(f"Found potential duplicate by affected items: {item.get('id')}")
                    return True

        return False

    def _create_beads_item(self, pattern: FailurePattern) -> str | None:
        """Create a beads item for the given pattern."""
        try:
            beads_dict = pattern.to_beads_dict()
            title = beads_dict["title"]
            description = beads_dict["description"]
            priority = beads_dict["priority"]
            labels = beads_dict["labels"]

            # Build the create command
            args = [
                "create",
                "--type", "bug",
                "--priority", str(priority),
                title,
            ]

            # Add labels
            for label in labels:
                args.extend(["--label", label])

            # Run create command
            result = _run_bd(args, check=False, timeout=30)

            if result.returncode != 0:
                logger.error(f"Failed to create beads item: {result.stderr}")
                return None

            # Extract item ID from output
            # Format is typically: "Created issue <id>"
            output = result.stdout.strip()
            item_id = self._extract_item_id(output)

            if not item_id:
                logger.warning(f"Could not extract item ID from output: {output}")
                return None

            # Update description with detailed content
            self._update_item_description(item_id, description)

            return item_id

        except Exception as e:
            logger.error(f"Error creating beads item: {e}", exc_info=True)
            return None

    def _extract_item_id(self, output: str) -> str | None:
        """Extract item ID from beads create output."""
        # Try to find pattern like "Created issue <id>" or just extract the ID
        import re

        # Try pattern: "Created issue ID-123"
        match = re.search(r"Created\s+(?:issue|item)\s+([A-Za-z0-9_-]+)", output, re.IGNORECASE)
        if match:
            return match.group(1)

        # Try pattern: just the ID at the end
        match = re.search(r"\b([A-Za-z0-9_-]{6,})\b", output)
        if match:
            return match.group(1)

        return None

    def _update_item_description(self, item_id: str, description: str) -> bool:
        """Update item description with detailed content."""
        try:
            # Use beads update with description
            # Some beads CLIs support --description, others need interactive mode
            # Try the simple approach first
            result = _run_bd(
                ["update", item_id, "--description", description],
                check=False,
                timeout=30,
            )

            if result.returncode == 0:
                return True

            # If that failed, try alternative: update via comments
            logger.debug("Direct description update failed, adding as comment")
            result = _run_bd(
                ["comments", item_id, "--add", description],
                check=False,
                timeout=30,
            )

            return result.returncode == 0

        except Exception as e:
            logger.warning(f"Failed to update description for {item_id}: {e}")
            return False
