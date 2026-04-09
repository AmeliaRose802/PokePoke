"""Session lifecycle helpers: finalization, post-mortem, and result recording."""

import contextlib
import logging
import time
from pathlib import Path

from pokepoke.beads.beads import get_beads_stats
from pokepoke.beads.beads_item_stats_store import record_item_attempt, record_item_completed
from pokepoke.config import load_config
from pokepoke.desktop import terminal_ui
from pokepoke.desktop.terminal_ui import clear_terminal_banner
from pokepoke.git.merge_queue import get_merge_queue
from pokepoke.git.state_branch import commit_state_branch
from pokepoke.maintenance.maintenance_scheduler import run_periodic_maintenance
from pokepoke.maintenance.maintenance_state import increment_items_completed
from pokepoke.models.model_history import append_model_history_entry
from pokepoke.models.model_stats_store import record_completion
from pokepoke.stats.session_stats_registry import set_current_session_stats
from pokepoke.stats.stats import print_stats
from pokepoke.types import BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.utils.logging_utils import RunLogger
from pokepoke.utils.shutdown import is_shutting_down

logger = logging.getLogger(__name__)


def _finalize_session(session_stats: SessionStats, start_time: float, items_completed: int,
                      total_requests: int, run_logger: RunLogger, run_post_mortem: bool = False) -> None:
    """Collect ending stats, print summary, and clean up UI."""
    if run_post_mortem:
        _run_post_mortem_if_enabled(run_logger, session_stats)

    end_time = time.time()
    terminal_ui.ui.set_session_end_time(end_time)
    try:
        session_stats.set_ending_beads_stats(None if is_shutting_down() else get_beads_stats())
    except KeyboardInterrupt:
        logger.warning("⚠️  Stats collection interrupted, skipping...")
        session_stats.set_ending_beads_stats(None)
    with contextlib.suppress(Exception):
        mq = get_merge_queue()
        session_stats.record_merge_queue_stats(mq.stats)
        mq.reset_stats()
    elapsed = end_time - start_time

    # Commit state branch with final session state
    try:
        cfg = load_config()
        commit_state_branch(config=cfg.state_branch, cwd=Path.cwd(), force=True)
    except Exception as e:
        logger.warning(f"Failed to commit state branch on finalize: {e}")

    print_stats(items_completed, total_requests, elapsed, session_stats)
    run_logger.finalize(items_completed, total_requests, elapsed, session_stats)
    set_current_session_stats(None)
    clear_terminal_banner()


def _run_post_mortem_if_enabled(run_logger: RunLogger, session_stats: SessionStats) -> None:
    """Run post-mortem agent if enabled in configuration."""
    try:
        from pokepoke.agents.post_mortem_agent import run_post_mortem_agent
        logger.info("\n🔍 Running post-mortem agent...")
        pm_result = run_post_mortem_agent(
            run_logs_dir=run_logger.get_run_dir(),
            run_logger=run_logger,
            session_stats=session_stats,
        )
        if pm_result.get("items_created", 0) > 0:
            logger.info(f"Post-mortem created {pm_result['items_created']} issue(s), fixed {pm_result.get('items_fixed', 0)}")
    except Exception as e:
        logger.error(f"Post-mortem agent failed: {e}", exc_info=True)
        run_logger.log_orchestrator(f"Post-mortem error: {e}", level="ERROR")


def _should_run_post_mortem(session_stats: SessionStats, reason: str = "") -> bool:
    """Determine if post-mortem should run based on session state and reason."""
    cfg = load_config()
    if not cfg.post_mortem.enabled:
        return False

    if "circuit" in reason.lower() or "consecutive" in reason.lower():
        logger.debug(f"Post-mortem triggered: {reason}")
        return True

    # Check success rate - run post-mortem if < 50% success in non-trivial runs
    total_work_runs = session_stats.agent_run_counts.get("work", 0)
    items_failed = total_work_runs - session_stats.items_completed
    if total_work_runs > 3:
        success_rate = session_stats.items_completed / max(1, total_work_runs)
        if success_rate < 0.5:
            logger.debug(f"Post-mortem triggered: low success rate ({success_rate:.1%}, {items_failed} failures)")
            return True

    return False


def _record_item_result(selected_item: BeadsWorkItem, result: WorkItemResult,
                        session_stats: SessionStats, run_logger: RunLogger) -> tuple[bool, int]:
    """Record the result of processing a single work item."""
    if result.request_count > 1:
        session_stats.record_retries(result.request_count - 1)
    session_stats.record_agent_run("work")
    session_stats.record_agent_run("cleanup", result.cleanup_agent_runs)
    session_stats.record_agent_run("gate", result.gate_agent_runs)
    if result.stats:
        session_stats.record_agent_stats(result.stats)
    if result.model_completion:
        session_stats.record_model_completion(result.model_completion)
        record_completion(result.model_completion)
        append_model_history_entry(item=selected_item, model_completion=result.model_completion,
                                   success=result.success, request_count=result.request_count,
                                   gate_runs=result.gate_agent_runs, item_stats=result.stats)

    # Record per-item quality metrics
    s = result.stats
    item_metrics = record_item_attempt(
        selected_item.id, success=result.success,
        tokens_used=(s.input_tokens + s.output_tokens) if s else 0,
        duration_seconds=s.wall_duration if s else 0.0,
        failure_reason=result.failure_reason,
        attention_threshold=load_config().needs_human_attention_threshold)
    if item_metrics.get("needs_human_attention"):
        logger.warning(f"⚠️  Item {selected_item.id} flagged as needs-human-attention ({item_metrics['consecutive_failures']} consecutive failures)")

    items_completed = 0
    if result.success:
        items_completed = session_stats.record_completion(selected_item, agent_type="work")
        beads_summary = record_item_completed(selected_item.id, agent_type="work")
        session_stats.set_lifetime_beads_item_totals(
            created=int(beads_summary.get("total_created", 0)),
            completed=int(beads_summary.get("total_completed", 0)))
        total_count = increment_items_completed(repo_id=str(Path.cwd()))
        logger.info(f"\n📈 Items completed this session: {items_completed}\n📈 Total (lifetime): {total_count}\n📈 Beads created (lifetime): {session_stats.lifetime_items_created}")
        run_logger.log_orchestrator(f"Items completed this session: {items_completed}")
        run_periodic_maintenance(total_count, session_stats, run_logger, repo_id=str(Path.cwd()))

        # Commit state branch periodically based on config
        cfg = load_config()
        if cfg.state_branch.enabled and total_count % cfg.state_branch.auto_commit_interval_items == 0:
            try:
                if commit_state_branch(config=cfg.state_branch, cwd=Path.cwd()):
                    logger.info(f"✅ State branch committed (every {cfg.state_branch.auto_commit_interval_items} items)")
            except Exception as e:
                logger.warning(f"Failed to commit state branch: {e}")
    return result.success, session_stats.items_completed
