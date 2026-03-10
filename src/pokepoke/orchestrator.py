"""PokePoke Orchestrator - Main entry point for autonomous and interactive modes."""
import atexit
import contextlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pokepoke.beads import get_ready_work_items, get_beads_stats
from pokepoke.types import AgentStats, SessionStats, BeadsWorkItem, WorkItemResult
from pokepoke.stats import print_stats
from pokepoke.workflow import process_work_item
from pokepoke.work_item_selection import select_work_item
from pokepoke.logging_utils import RunLogger, configure_logging
from pokepoke.agent_names import initialize_agent_name
from pokepoke.agent_context import get_agent_name
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner, clear_terminal_banner
from pokepoke import terminal_ui
from pokepoke.maintenance_state import increment_items_completed
from pokepoke.repo_check import check_and_commit_main_repo
from pokepoke.maintenance_scheduler import run_periodic_maintenance
from pokepoke.shutdown import is_shutting_down, request_shutdown, should_stop_after_current, cancel_stop_after_current
from pokepoke.model_stats_store import record_completion
from pokepoke.model_history import append_model_history_entry
from pokepoke.config import load_config
from pokepoke.signal_handlers import register_shutdown_handlers, unregister_shutdown_handlers
from pokepoke.performance_monitor import run_iteration_checks

logger = logging.getLogger(__name__)


def _finalize_session(
    session_stats: SessionStats, start_time: float,
    items_completed: int, total_requests: int, run_logger: RunLogger,
) -> None:
    """Collect ending stats, print summary, and clean up UI."""
    end_time = time.time()
    terminal_ui.ui.set_session_end_time(end_time)  # Stop desktop UI clock
    try:
        session_stats.set_ending_beads_stats(None if is_shutting_down() else get_beads_stats())
    except KeyboardInterrupt:
        print("⚠️  Stats collection interrupted, skipping...")
        session_stats.set_ending_beads_stats(None)
    # Capture merge queue performance metrics
    with contextlib.suppress(Exception):
        from pokepoke.merge_queue import get_merge_queue
        session_stats.record_merge_queue_stats(get_merge_queue().stats)
    elapsed = end_time - start_time
    print_stats(items_completed, total_requests, elapsed, session_stats)
    run_logger.finalize(items_completed, total_requests, elapsed, session_stats)
    from pokepoke.session_stats_registry import set_current_session_stats
    set_current_session_stats(None)
    clear_terminal_banner()


def _record_item_result(selected_item: BeadsWorkItem, result: WorkItemResult, session_stats: SessionStats, run_logger: RunLogger) -> tuple[bool, int]:
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
    items_completed = 0
    if result.success:
        items_completed = session_stats.record_completion(selected_item, agent_type="work")
        from pokepoke.beads_item_stats_store import record_item_completed
        beads_summary = record_item_completed(selected_item.id, agent_type="work")
        session_stats.set_lifetime_beads_item_totals(created=int(beads_summary.get("total_created", 0)), completed=int(beads_summary.get("total_completed", 0)))
        total_persistent_count = increment_items_completed(repo_id=str(Path.cwd()))
        print(f"\n📈 Items completed this session: {items_completed}\n📈 Total items completed (lifetime): {total_persistent_count}\n📈 Beads created (lifetime): {session_stats.lifetime_items_created}\n📈 Beads net delta (lifetime): {session_stats.lifetime_items_created - session_stats.lifetime_items_completed:+d}")
        run_logger.log_orchestrator(f"Items completed this session: {items_completed}")
        run_periodic_maintenance(total_persistent_count, session_stats, run_logger, repo_id=str(Path.cwd()))
    return result.success, session_stats.items_completed


@dataclass
class _OrchestratorContext:
    """Shared mutable state threaded through orchestrator phases."""
    agent_name: str
    mode_name: str
    run_logger: RunLogger
    main_repo_path: Path
    start_time: float
    session_stats: SessionStats
    failed_claim_ids: set[str]
    cfg: Any
    effective_parallel: int
    interactive: bool
    continuous: bool
    items_completed: int = 0
    total_requests: int = 0

    def finalize(self) -> None:
        """Shorthand to finalize session with current context state."""
        _finalize_session(
            self.session_stats, self.start_time,
            self.items_completed, self.total_requests, self.run_logger,
        )


def _setup_orchestrator(
    interactive: bool, continuous: bool,
    run_beta_first: bool, agent_name_override: str | None,
    max_parallel_agents: int,
) -> _OrchestratorContext:
    """Initialize agent identity, logging, signal handlers, beads recovery, and config."""
    agent_name = initialize_agent_name(custom_name=agent_name_override)
    os.environ['AGENT_NAME'] = agent_name
    from pokepoke.agent_context import set_agent_name
    set_agent_name(agent_name)
    mode_name = "Interactive" if interactive else "Autonomous"
    print(f"🎯 PokePoke {mode_name} Mode | 🤖 Agent: {agent_name}")
    print("=" * 50)
    set_terminal_banner(f"PokePoke {mode_name} - {agent_name}")
    terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", agent_name)

    run_logger = RunLogger()
    run_dir = run_logger.get_run_dir()
    configure_logging(run_dir / 'debug.log')
    print(f"📝 Run ID: {run_logger.get_run_id()} | 📁 Logs: {run_dir}")
    terminal_ui.ui.set_logs_dir(str(run_dir))
    run_logger.log_orchestrator(f"PokePoke started in {mode_name} mode with agent name: {agent_name}")
    register_shutdown_handlers(run_logger)
    atexit.register(lambda: print(f"\n📁 Logs saved to: {run_dir}"))
    main_repo_path = Path.cwd()
    print(f"📁 Repository: {main_repo_path}")
    run_logger.log_orchestrator(f"Repository: {main_repo_path}")
    start_time = time.time()
    session_stats = SessionStats(agent_stats=AgentStats())
    from pokepoke.session_stats_registry import set_current_session_stats
    set_current_session_stats(session_stats)

    # Backfill missing beads item creation events for Desktop UI accuracy
    from pokepoke.beads_item_stats_backfill import backfill_from_beads_db
    try:
        backfill_result = backfill_from_beads_db(silent=True)
        if backfill_result["backfilled"] > 0:
            print(f"✅ Backfilled {backfill_result['backfilled']} beads item creation events")
    except Exception as e:
        logger.warning(f"Failed to backfill beads item stats: {e}")
    from pokepoke.beads_item_stats_store import get_summary as _get_beads_summary
    s = _get_beads_summary()
    session_stats.set_lifetime_beads_item_totals(
        created=int(s.get("total_created", 0)),
        completed=int(s.get("total_completed", 0)),
    )
    # Recover any items that failed to unassign in previous runs
    from pokepoke.beads import retry_failed_unassigns, get_failed_unassign_count
    stuck_count = get_failed_unassign_count()
    if stuck_count > 0:
        print(f"🔧 Recovering {stuck_count} item(s) stuck from failed unassigns...")
        recovered = retry_failed_unassigns()
        if recovered:
            run_logger.log_orchestrator(f"Recovered {recovered}/{stuck_count} stuck item(s)")
    session_stats.set_starting_beads_stats(get_beads_stats())
    terminal_ui.ui.set_session_start_time(start_time)
    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

    if run_beta_first:
        print("\n🧪 Running Beta Tester at startup...")
        run_logger.log_orchestrator("Running Beta Tester at startup")
        from pokepoke.agent_runner import run_beta_tester
        beta_stats = run_beta_tester(repo_root=main_repo_path)
        if beta_stats:
            session_stats.record_agent_stats(beta_stats)
        print("✅ Beta Tester completed\n")
    # Resolve effective parallelism: CLI arg > config > 1
    cfg = load_config()
    effective_parallel = max(1, max_parallel_agents if max_parallel_agents > 1 else cfg.max_parallel_agents)
    if effective_parallel > 1 and interactive:
        print(f"⚠️  Parallel mode (--max-agents {effective_parallel}) requires autonomous mode; forcing parallel=1")
        effective_parallel = 1
    if effective_parallel > 1:
        print(f"🔀 Parallel mode: up to {effective_parallel} concurrent agents")
        run_logger.log_orchestrator(f"Parallel mode enabled: max_parallel_agents={effective_parallel}")

    return _OrchestratorContext(
        agent_name=agent_name, mode_name=mode_name, run_logger=run_logger,
        main_repo_path=main_repo_path, start_time=start_time,
        session_stats=session_stats, failed_claim_ids=set(), cfg=cfg,
        effective_parallel=effective_parallel, interactive=interactive,
        continuous=continuous,
    )


def _run_preflight(ctx: _OrchestratorContext) -> int | None:
    """Run pre-flight health checks. Returns exit code to stop, or None to continue."""
    print("\n🔍 Running pre-flight health checks...")
    ctx.run_logger.log_polling("Running pre-flight health checks")

    from pokepoke.parallel_support import handle_preflight_checks
    should_continue, _is_critical = handle_preflight_checks(
        ctx.main_repo_path, ctx.run_logger, cfg=ctx.cfg,
    )
    if not should_continue:
        terminal_ui.ui.stop_and_capture()
        ctx.finalize()
        return 1
    return None


def _run_main_loop(ctx: _OrchestratorContext) -> int:
    """Sequential work-selection and dispatch loop. Returns process exit code."""
    while not is_shutting_down():
        iter_start = time.monotonic()

        exit_code = _run_preflight(ctx)
        if exit_code is not None:
            return exit_code

        print("\n\ud83d\udd0d Checking main repository status...")
        ctx.run_logger.log_polling("Checking main repository status")
        if not check_and_commit_main_repo(ctx.main_repo_path, ctx.run_logger):
            ctx.run_logger.log_orchestrator("Main repo check failed", level="ERROR")
            return 1

        print("\nFetching ready work from beads...")
        ctx.run_logger.log_polling("Fetching ready work from beads")
        ready_items = get_ready_work_items()
        if ctx.interactive:
            terminal_ui.ui.stop()
        selected_item = select_work_item(ready_items, ctx.interactive, skip_ids=ctx.failed_claim_ids)
        if ctx.interactive:
            terminal_ui.ui.start()

        if selected_item is None:
            terminal_ui.ui.stop_and_capture()
            print("\n👋 Exiting PokePoke - no work items available.")
            ctx.run_logger.log_orchestrator("No work items available - exiting")
            ctx.finalize()
            return 0

        ctx.run_logger.log_orchestrator(f"Selected item: {selected_item.id} - {selected_item.title}")
        banner = format_work_item_banner(selected_item.id, selected_item.title)
        set_terminal_banner(banner)
        terminal_ui.ui.update_header(selected_item.id, selected_item.title)

        agent_id = selected_item.id
        display_name = get_agent_name(default="pokepoke")
        terminal_ui.ui.push_agent_status(
            agent_id, display_name, iteration=1, status="running",
            work_item_id=selected_item.id, work_item_title=selected_item.title,
            agent_type="work",
        )
        success = False
        try:
            with terminal_ui.ui.agent_output_for(agent_id):
                wi_result = process_work_item(
                    selected_item, ctx.interactive,
                    run_logger=ctx.run_logger, agent_id=agent_id,
                )
            success = wi_result.success
        finally:
            terminal_ui.ui.push_agent_status(
                agent_id, display_name, iteration=1,
                status="success" if success else "failed",
                work_item_id=selected_item.id, work_item_title=selected_item.title,
                agent_type="work",
            )

        if not wi_result.success and wi_result.request_count == 0:
            ctx.failed_claim_ids.add(selected_item.id)
            ctx.run_logger.log_orchestrator(
                f"Item {selected_item.id} failed to claim, added to skip list "
                f"({len(ctx.failed_claim_ids)} skipped)",
            )
        elif wi_result.success:
            ctx.failed_claim_ids.clear()

        ctx.total_requests += wi_result.request_count
        _record_item_result(selected_item, wi_result, ctx.session_stats, ctx.run_logger)
        ctx.items_completed = ctx.session_stats.items_completed
        terminal_ui.ui.update_stats(ctx.session_stats, time.time() - ctx.start_time)

        # Performance threshold checks
        run_iteration_checks(time.monotonic() - iter_start, wi_result.success)

        if should_stop_after_current():
            cancel_stop_after_current()
            terminal_ui.ui.stop_and_capture()
            print("\n⏸️  Stopping after current item (user requested).")
            ctx.run_logger.log_orchestrator("Stop after current item requested - exiting")
            ctx.finalize()
            return 0

        if not ctx.continuous:
            terminal_ui.ui.stop_and_capture()
            ctx.finalize()
            return 0 if success else 1

        if ctx.interactive:
            set_terminal_banner(f"PokePoke {ctx.mode_name} - {ctx.agent_name}")
            terminal_ui.ui.update_header("PokePoke", f"{ctx.mode_name} Mode", "Waiting...")
            terminal_ui.ui.stop()
            cont = input("\nProcess another item? [Y/n]: ").strip().lower()
            terminal_ui.ui.start()
            if cont and cont != 'y':
                terminal_ui.ui.stop_and_capture()
                print("\n👋 Exiting PokePoke.")
                ctx.finalize()
                return 0
        else:
            terminal_ui.ui.update_header("PokePoke", f"{ctx.mode_name} Mode", "Sleeping...")
            print("\n⏳ Waiting 5 seconds before next iteration...")
            for _ in range(10):
                if is_shutting_down():
                    break
                time.sleep(0.5)

    # Shutdown requested - clean exit
    terminal_ui.ui.stop_and_capture()
    print("\n\ud83d\udc4b Shutdown requested - exiting PokePoke.")
    ctx.finalize()
    return 0


def run_orchestrator(
    interactive: bool = True, continuous: bool = False,
    run_beta_first: bool = False, agent_name_override: str | None = None,
    max_parallel_agents: int = 1,
) -> int:
    """Main orchestrator entry point (interactive or autonomous)."""
    # UI is started by run_with_orchestrator - just update header
    terminal_ui.ui.update_header("PokePoke", f"Initializing {interactive and 'Interactive' or 'Autonomous'} Mode...")
    try:
        ctx = _setup_orchestrator(
            interactive, continuous, run_beta_first,
            agent_name_override, max_parallel_agents,
        )
        if ctx.effective_parallel > 1:
            from pokepoke.parallel import run_parallel_loop
            exit_code = run_parallel_loop(
                effective_parallel=ctx.effective_parallel,
                mode_name=ctx.mode_name,
                main_repo_path=ctx.main_repo_path,
                failed_claim_ids=ctx.failed_claim_ids,
                session_stats=ctx.session_stats,
                start_time=ctx.start_time,
                run_logger=ctx.run_logger,
                continuous=ctx.continuous,
                record_fn=_record_item_result,
                finalize_fn=_finalize_session,
                cli_override=(max_parallel_agents > 1),
            )
            ctx.items_completed = ctx.session_stats.items_completed
            terminal_ui.ui.stop_and_capture()
            if exit_code is not None:
                return exit_code
        else:
            return _run_main_loop(ctx)
        # Shutdown requested - clean exit
        terminal_ui.ui.stop_and_capture()
        ctx.finalize()
        return 0
    except KeyboardInterrupt:
        request_shutdown()
        terminal_ui.ui.stop_and_capture()
        print("\n\n⚠️  Interrupted by user (Ctrl+C)")
        print("📊 Collecting final statistics...")
        print("\n👋 Exiting PokePoke.")
        ctx.finalize()
        return 0
    except Exception as e:
        terminal_ui.ui.stop_and_capture()
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        ctx.run_logger.log_orchestrator(f"Error: {e}", level="ERROR")
        ctx.finalize()
        return 1
    finally:
        terminal_ui.ui.stop()
        try:
            from pokepoke.merge_queue import get_merge_queue
            mq = get_merge_queue()
            if mq.is_running:
                mq.shutdown(timeout=10.0)
        except Exception as e:
            logger.debug(f"Failed to shutdown merge queue during cleanup: {e}")
        with contextlib.suppress(Exception):
            unregister_shutdown_handlers()


if __name__ == "__main__":
    import sys
    from pokepoke.__main__ import main
    sys.exit(main())
