"""Post-mortem agent - analyzes failures, files issues, and attempts self-healing."""

import logging
import time
from pathlib import Path
from typing import Any

from pokepoke.agents.post_mortem_analyzer import FailurePattern, LogAnalyzer
from pokepoke.agents.post_mortem_issue_creator import BeadsIssueCreator
from pokepoke.beads.beads import get_ready_work_items
from pokepoke.config import ProjectConfig, load_config
from pokepoke.orchestration.workflow import process_work_item
from pokepoke.types import SessionStats
from pokepoke.utils.logging_utils import RunLogger

logger = logging.getLogger(__name__)


class PostMortemAgent:
    """Coordinates post-mortem analysis, issue filing, and self-healing attempts."""

    def __init__(
        self,
        run_logs_dir: Path,
        config: ProjectConfig | None = None,
        run_logger: RunLogger | None = None,
    ):
        """Initialize the post-mortem agent."""
        self.run_logs_dir = run_logs_dir
        self.config = config or load_config()
        self.run_logger = run_logger
        self.patterns: list[FailurePattern] = []
        self.created_item_ids: list[str] = []

    def run(self, session_stats: SessionStats | None = None) -> dict[str, Any]:
        """Execute post-mortem analysis and self-healing workflow."""
        if not self.config.post_mortem.enabled:
            logger.info("Post-mortem agent disabled in configuration")
            return {"enabled": False, "patterns_found": 0, "items_created": 0}

        logger.info("\n" + "=" * 60)
        logger.info("🔍 POST-MORTEM AGENT STARTED")
        logger.info("=" * 60)

        start_time = time.time()
        timeout_seconds = self.config.post_mortem.timeout_minutes * 60

        # Phase 1: ANALYZE
        logger.info("\n📊 Phase 1: Analyzing run logs...")
        if self.run_logger:
            self.run_logger.log_orchestrator("Post-mortem: Starting log analysis")

        analyzer = LogAnalyzer(
            self.run_logs_dir,
            min_pattern_frequency=self.config.post_mortem.min_pattern_frequency,
        )
        self.patterns = analyzer.analyze()

        if not self.patterns:
            logger.info("✅ No failure patterns identified - clean run!")
            if self.run_logger:
                self.run_logger.log_orchestrator("Post-mortem: No patterns found")
            return {
                "enabled": True,
                "patterns_found": 0,
                "items_created": 0,
                "items_fixed": 0,
                "duration_seconds": time.time() - start_time,
            }

        logger.info(f"\n{analyzer.get_summary()}\n")
        if self.run_logger:
            self.run_logger.log_orchestrator(f"Post-mortem: Found {len(self.patterns)} pattern(s)")

        # Phase 2: FILE
        logger.info("📝 Phase 2: Filing beads items for identified patterns...")
        issue_creator = BeadsIssueCreator(beads_backend=self.config.repos[0].beads_backend if self.config.repos else "bd")

        # Limit to max_items
        patterns_to_file = self.patterns[:self.config.post_mortem.max_items]
        if len(self.patterns) > self.config.post_mortem.max_items:
            logger.info(f"Limiting to top {self.config.post_mortem.max_items} patterns (out of {len(self.patterns)})")

        self.created_item_ids = issue_creator.file_issues(patterns_to_file)

        if not self.created_item_ids:
            logger.info("ℹ️  No new items created (all patterns already filed or filing failed)")
            if self.run_logger:
                self.run_logger.log_orchestrator("Post-mortem: No items created (duplicates or errors)")
            return {
                "enabled": True,
                "patterns_found": len(self.patterns),
                "items_created": 0,
                "items_fixed": 0,
                "duration_seconds": time.time() - start_time,
            }

        logger.info(f"\n✅ Created {len(self.created_item_ids)} beads item(s): {', '.join(self.created_item_ids)}")
        if self.run_logger:
            self.run_logger.log_orchestrator(f"Post-mortem: Created {len(self.created_item_ids)} item(s): {', '.join(self.created_item_ids)}")

        # Phase 3: PRIORITIZE (already done by analyzer based on severity)
        logger.info("\n🎯 Phase 3: Items prioritized by severity and impact")
        for i, item_id in enumerate(self.created_item_ids, 1):
            pattern = patterns_to_file[i-1] if i-1 < len(patterns_to_file) else None
            if pattern:
                logger.info(f"  {i}. {item_id} [{pattern.severity}] - {pattern.pattern_type}")

        # Phase 4: RESUME (attempt to fix filed items)
        logger.info("\n🔧 Phase 4: Attempting self-healing for filed items...")
        elapsed = time.time() - start_time
        remaining_time = timeout_seconds - elapsed

        if remaining_time <= 60:
            logger.warning(f"⚠️  Insufficient time remaining ({remaining_time:.0f}s) - skipping self-heal phase")
            if self.run_logger:
                self.run_logger.log_orchestrator("Post-mortem: Skipped self-heal (timeout)")
            return {
                "enabled": True,
                "patterns_found": len(self.patterns),
                "items_created": len(self.created_item_ids),
                "items_fixed": 0,
                "duration_seconds": time.time() - start_time,
                "timeout_reached": True,
            }

        fixed_count = self._attempt_self_healing(remaining_time, session_stats)

        # Phase 5: SHUTDOWN
        total_duration = time.time() - start_time
        logger.info("\n" + "=" * 60)
        logger.info("🏁 POST-MORTEM AGENT COMPLETED")
        logger.info(f"Patterns found: {len(self.patterns)}")
        logger.info(f"Items created: {len(self.created_item_ids)}")
        logger.info(f"Items fixed: {fixed_count}")
        logger.info(f"Duration: {total_duration:.1f}s / {timeout_seconds}s")
        logger.info("=" * 60 + "\n")

        if self.run_logger:
            self.run_logger.log_orchestrator(
                f"Post-mortem completed: {len(self.patterns)} patterns, "
                f"{len(self.created_item_ids)} items created, {fixed_count} fixed"
            )

        return {
            "enabled": True,
            "patterns_found": len(self.patterns),
            "items_created": len(self.created_item_ids),
            "items_fixed": fixed_count,
            "duration_seconds": total_duration,
            "created_item_ids": self.created_item_ids,
        }

    def _attempt_self_healing(self, timeout_seconds: float, session_stats: SessionStats | None) -> int:
        """Attempt to process newly-filed post-mortem items."""
        logger.info(f"Time available for self-healing: {timeout_seconds:.0f}s")

        if not self.created_item_ids:
            return 0

        # Fetch fresh work items and filter to only post-mortem items
        ready_items = get_ready_work_items()
        if ready_items is None:
            logger.warning("Failed to fetch ready work items for self-healing")
            return 0

        # Filter to only our newly-created post-mortem items that are ready
        post_mortem_items = [
            item for item in ready_items
            if item.id in self.created_item_ids
        ]

        if not post_mortem_items:
            logger.info("ℹ️  No post-mortem items in ready state (may have dependencies)")
            return 0

        logger.info(f"Found {len(post_mortem_items)} post-mortem item(s) ready to process")

        fixed_count = 0
        start_time = time.time()

        for item in post_mortem_items:
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                logger.warning(f"⏱️  Timeout reached ({elapsed:.0f}s/{timeout_seconds:.0f}s) - stopping self-heal")
                break

            logger.info(f"\n🔧 Attempting to fix: {item.id} - {item.title}")
            if self.run_logger:
                self.run_logger.log_orchestrator(f"Post-mortem self-heal: Processing {item.id}")

            try:
                # Process the item with autonomous mode (non-interactive)
                result = process_work_item(
                    item,
                    interactive=False,
                    run_logger=self.run_logger,
                    agent_id=f"post-mortem-{item.id}",
                )

                if result.success:
                    fixed_count += 1
                    logger.info(f"✅ Successfully fixed: {item.id}")
                    if self.run_logger:
                        self.run_logger.log_orchestrator(f"Post-mortem: Fixed {item.id}")

                    # Record in session stats if available
                    if session_stats:
                        session_stats.record_completion(item, agent_type="post-mortem")
                else:
                    logger.warning(f"❌ Failed to fix: {item.id} - {result.failure_reason}")
                    if self.run_logger:
                        self.run_logger.log_orchestrator(f"Post-mortem: Failed to fix {item.id}")

            except Exception as e:
                logger.error(f"Error processing {item.id}: {e}", exc_info=True)
                if self.run_logger:
                    self.run_logger.log_orchestrator(f"Post-mortem: Error on {item.id}: {e}", level="ERROR")

        return fixed_count


def run_post_mortem_agent(
    run_logs_dir: Path,
    config: ProjectConfig | None = None,
    run_logger: RunLogger | None = None,
    session_stats: SessionStats | None = None,
) -> dict[str, Any]:
    """Run the post-mortem agent (convenience function)."""
    agent = PostMortemAgent(run_logs_dir, config, run_logger)
    return agent.run(session_stats)
