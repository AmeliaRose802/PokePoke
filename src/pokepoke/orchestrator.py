"""PokePoke Orchestrator - Main entry point for autonomous and interactive modes."""

import argparse
import atexit
import contextlib
import logging
import os
import sys
import time
from pathlib import Path

from pokepoke.beads import get_ready_work_items, get_beads_stats
from pokepoke.types import AgentStats, SessionStats, BeadsWorkItem, WorkItemResult
from pokepoke.stats import print_stats
from pokepoke.workflow import process_work_item
from pokepoke.work_item_selection import select_work_item
from pokepoke.logging_utils import RunLogger
from pokepoke.agent_names import initialize_agent_name
from pokepoke.agent_context import get_agent_name
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner, clear_terminal_banner
from pokepoke import terminal_ui
from pokepoke.maintenance_state import increment_items_completed
from pokepoke.repo_check import check_and_commit_main_repo
from pokepoke.maintenance import run_periodic_maintenance
from pokepoke.shutdown import is_shutting_down, request_shutdown, should_stop_after_current, cancel_stop_after_current
from pokepoke.model_stats_store import record_completion
from pokepoke.model_history import append_model_history_entry
from pokepoke.config import load_config
from pokepoke.signal_handlers import register_shutdown_handlers, unregister_shutdown_handlers

logger = logging.getLogger(__name__)


def _finalize_session(
    session_stats: SessionStats, start_time: float,
    items_completed: int, total_requests: int, run_logger: RunLogger,
) -> None:
    """Collect ending stats, print summary, and clean up UI."""
    end_time = time.time()
    terminal_ui.ui.set_session_end_time(end_time)  # Stop desktop UI clock
    try:
        session_stats.set_ending_beads_stats(get_beads_stats())
    except KeyboardInterrupt:
        print("ΓÜá∩╕Å  Stats collection interrupted, skipping...")
        session_stats.set_ending_beads_stats(None)
    elapsed = end_time - start_time
    print_stats(items_completed, total_requests, elapsed, session_stats)
    run_logger.finalize(items_completed, total_requests, elapsed, session_stats)
    from pokepoke.session_stats_registry import set_current_session_stats
    set_current_session_stats(None)
    clear_terminal_banner()


def _record_item_result(
    selected_item: BeadsWorkItem, result: WorkItemResult,
    session_stats: SessionStats, run_logger: RunLogger,
) -> tuple[bool, int]:
    """Record the result of processing a single work item.

    Returns:
        (success, items_completed) after recording.
    """
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
        append_model_history_entry(
            item=selected_item,
            model_completion=result.model_completion,
            success=result.success,
            request_count=result.request_count,
            gate_runs=result.gate_agent_runs,
            item_stats=result.stats,
        )

    items_completed = 0
    if result.success:
        items_completed = session_stats.record_completion(selected_item, agent_type="work")
        from pokepoke.beads_item_stats_store import record_item_completed
        beads_summary = record_item_completed(selected_item.id, agent_type="work")
        session_stats.set_lifetime_beads_item_totals(created=int(beads_summary.get("total_created", 0)), completed=int(beads_summary.get("total_completed", 0)))

        total_persistent_count = increment_items_completed()
        print(f"\n≡ƒôê Items completed this session: {items_completed}\n≡ƒôê Total items completed (lifetime): {total_persistent_count}\n≡ƒôê Beads created (lifetime): {session_stats.lifetime_items_created}\n≡ƒôê Beads net delta (lifetime): {session_stats.lifetime_items_created - session_stats.lifetime_items_completed:+d}")
        run_logger.log_orchestrator(f"Items completed this session: {items_completed}")
        run_periodic_maintenance(total_persistent_count, session_stats, run_logger)

    return result.success, session_stats.items_completed


def run_orchestrator(
    interactive: bool = True, continuous: bool = False,
    run_beta_first: bool = False, agent_name_override: str | None = None,
    max_parallel_agents: int = 1,
) -> int:
    """Main orchestrator loop (interactive or autonomous)."""
    # UI is started by run_with_orchestrator - just update header
    terminal_ui.ui.update_header("PokePoke", f"Initializing {interactive and 'Interactive' or 'Autonomous'} Mode...")
    try:
        agent_name = initialize_agent_name(custom_name=agent_name_override)
        os.environ['AGENT_NAME'] = agent_name
        from pokepoke.agent_context import set_agent_name
        set_agent_name(agent_name)
        mode_name = "Interactive" if interactive else "Autonomous"
        print(f"≡ƒÄ» PokePoke {mode_name} Mode | ≡ƒñû Agent: {agent_name}")
        print("=" * 50)
        set_terminal_banner(f"PokePoke {mode_name} - {agent_name}")
        terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", agent_name)

        run_logger = RunLogger()
        run_id = run_logger.get_run_id()
        run_dir = run_logger.get_run_dir()
        print(f"≡ƒô¥ Run ID: {run_id} | ≡ƒôü Logs: {run_dir}")
        terminal_ui.ui.set_logs_dir(str(run_dir))
        run_logger.log_orchestrator(f"PokePoke started in {mode_name} mode with agent name: {agent_name}")

        register_shutdown_handlers(run_logger)
        run_logger.log_orchestrator("Signal handlers registered for graceful shutdown logging")

        atexit.register(lambda: print(f"\n≡ƒôü Logs saved to: {run_dir}"))

        main_repo_path = Path.cwd()
        print(f"≡ƒôü Repository: {main_repo_path}")
        run_logger.log_orchestrator(f"Repository: {main_repo_path}")

        start_time = time.time()
        items_completed = 0
        total_requests = 0
        session_stats = SessionStats(agent_stats=AgentStats())
        from pokepoke.session_stats_registry import set_current_session_stats
        set_current_session_stats(session_stats)

        # Backfill any missing beads item creation events from the beads database
        # This ensures the Desktop UI's "Lifetime beads throughput" ADDED count is accurate
        from pokepoke.beads_item_stats_backfill import backfill_from_beads_db
        try:
            backfill_result = backfill_from_beads_db(silent=True)
            if backfill_result["backfilled"] > 0:
                print(f"✅ Backfilled {backfill_result['backfilled']} beads item creation events")
                run_logger.log_orchestrator(f"Backfilled {backfill_result['backfilled']} beads item creation events")
        except Exception as e:
            logger.warning(f"Failed to backfill beads item stats: {e}")
            run_logger.log_orchestrator(f"Failed to backfill beads item stats: {e}", level="WARNING")

        from pokepoke.beads_item_stats_store import get_summary as _get_beads_summary
        s = _get_beads_summary()
        session_stats.set_lifetime_beads_item_totals(created=int(s.get("total_created", 0)), completed=int(s.get("total_completed", 0)))

        print("≡ƒôè Recording starting beads statistics...")
        run_logger.log_orchestrator("Recording starting beads statistics")
        session_stats.set_starting_beads_stats(get_beads_stats())
        terminal_ui.ui.set_session_start_time(start_time)
        terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

        if run_beta_first:
            print("\n≡ƒº¬ Running Beta Tester at startup...")
            run_logger.log_orchestrator("Running Beta Tester at startup")
            from pokepoke.agent_runner import run_beta_tester
            beta_stats = run_beta_tester(repo_root=main_repo_path)
            if beta_stats:
                session_stats.record_agent_stats(beta_stats)
            print("Γ£à Beta Tester completed\n")
        failed_claim_ids: set[str] = set()
        # Resolve effective parallelism: CLI arg > config > 1
        cfg = load_config()
        effective_parallel = max(1, max_parallel_agents if max_parallel_agents > 1 else cfg.max_parallel_agents)
        if effective_parallel > 1 and interactive:
            print(f"ΓÜá∩╕Å  Parallel mode (--max-agents {effective_parallel}) requires autonomous mode; forcing parallel=1")
            effective_parallel = 1
        if effective_parallel > 1:
            print(f"≡ƒöÇ Parallel mode: up to {effective_parallel} concurrent agents")
            run_logger.log_orchestrator(f"Parallel mode enabled: max_parallel_agents={effective_parallel}")
        # ΓöÇΓöÇ Parallel orchestrator loop ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        if effective_parallel > 1:
            from pokepoke.parallel import run_parallel_loop
            exit_code = run_parallel_loop(
                effective_parallel=effective_parallel,
                mode_name=mode_name,
                main_repo_path=main_repo_path,
                failed_claim_ids=failed_claim_ids,
                session_stats=session_stats,
                start_time=start_time,
                run_logger=run_logger,
                continuous=continuous,
                record_fn=_record_item_result,
                finalize_fn=_finalize_session,
            )
            items_completed = session_stats.items_completed
            terminal_ui.ui.stop_and_capture()
            if exit_code is not None:
                return exit_code
        # ΓöÇΓöÇ Sequential orchestrator loop (original behaviour) ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ
        else:
            while not is_shutting_down():
                print("\n\ud83d\udd0d Checking main repository status...")
                run_logger.log_orchestrator("Checking main repository status")
                if not check_and_commit_main_repo(main_repo_path, run_logger):
                    run_logger.log_orchestrator("Main repo check failed", level="ERROR")
                    return 1
                print("\nFetching ready work from beads...")
                run_logger.log_orchestrator("Fetching ready work from beads")
                ready_items = get_ready_work_items()
                if interactive:
                    terminal_ui.ui.stop()
                selected_item = select_work_item(ready_items, interactive, skip_ids=failed_claim_ids)
                if interactive:
                    terminal_ui.ui.start()
                if selected_item is None:
                    terminal_ui.ui.stop_and_capture()
                    print("\n≡ƒæï Exiting PokePoke - no work items available.")
                    run_logger.log_orchestrator("No work items available - exiting")
                    _finalize_session(session_stats, start_time, items_completed, total_requests, run_logger)
                    return 0
                run_logger.log_orchestrator(f"Selected item: {selected_item.id} - {selected_item.title}")
                banner = format_work_item_banner(selected_item.id, selected_item.title)
                set_terminal_banner(banner)
                terminal_ui.ui.update_header(selected_item.id, selected_item.title)

                agent_id = selected_item.id
                display_name = get_agent_name(default="pokepoke")
                terminal_ui.ui.push_agent_status(
                    agent_id,
                    display_name,
                    iteration=1,
                    status="running",
                    work_item_id=selected_item.id,
                    work_item_title=selected_item.title,
                )
                success = False
                try:
                    with terminal_ui.ui.agent_output_for(agent_id):
                        wi_result = process_work_item(selected_item, interactive, run_logger=run_logger, agent_id=agent_id)
                    success = wi_result.success
                finally:
                    terminal_ui.ui.push_agent_status(
                        agent_id,
                        display_name,
                        iteration=1,
                        status="success" if success else "failed",
                        work_item_id=selected_item.id,
                        work_item_title=selected_item.title,
                    )

                if not wi_result.success and wi_result.request_count == 0:
                    failed_claim_ids.add(selected_item.id)
                    run_logger.log_orchestrator(
                        f"Item {selected_item.id} failed to claim, added to skip list "
                        f"({len(failed_claim_ids)} skipped)"
                    )
                elif wi_result.success:
                    failed_claim_ids.clear()

                total_requests += wi_result.request_count
                _record_item_result(
                    selected_item, wi_result,
                    session_stats, run_logger,
                )
                items_completed = session_stats.items_completed
                terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
                # Check if user requested stop after current item
                if should_stop_after_current():
                    cancel_stop_after_current()
                    terminal_ui.ui.stop_and_capture()
                    print("\nΓÅ╕∩╕Å  Stopping after current item (user requested).")
                    run_logger.log_orchestrator("Stop after current item requested - exiting")
                    _finalize_session(session_stats, start_time, items_completed, total_requests, run_logger)
                    return 0

                if not continuous:
                    terminal_ui.ui.stop_and_capture()
                    _finalize_session(session_stats, start_time, items_completed, total_requests, run_logger)
                    return 0 if success else 1
                if interactive:
                    # Clear banner between items
                    set_terminal_banner(f"PokePoke {mode_name} - {agent_name}")
                    terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", "Waiting...")
                    terminal_ui.ui.stop()
                    cont = input("\nProcess another item? [Y/n]: ").strip().lower()
                    terminal_ui.ui.start()
                    if cont and cont != 'y':
                        terminal_ui.ui.stop_and_capture()
                        print("\n≡ƒæï Exiting PokePoke.")
                        _finalize_session(session_stats, start_time, items_completed, total_requests, run_logger)
                        return 0
                else:
                    terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", "Sleeping...")
                    print("\nΓÅ│ Waiting 5 seconds before next iteration...")
                    for _ in range(10):
                        if is_shutting_down():
                            break
                        time.sleep(0.5)
        # Shutdown requested - clean exit
        terminal_ui.ui.stop_and_capture()
        print("\n\ud83d\udc4b Shutdown requested - exiting PokePoke.")
        _finalize_session(session_stats, start_time, items_completed, total_requests, run_logger)
        return 0
    except KeyboardInterrupt:
        # Clean shutdown on Ctrl+C
        request_shutdown()
        terminal_ui.ui.stop_and_capture()
        print("\n\nΓÜá∩╕Å  Interrupted by user (Ctrl+C)")
        print("≡ƒôè Collecting final statistics...")
        print("\n≡ƒæï Exiting PokePoke.")
        _finalize_session(session_stats, start_time, items_completed, total_requests, run_logger)
        return 0
    except Exception as e:
        terminal_ui.ui.stop_and_capture()
        print(f"\nΓ¥î Error: {e}")
        import traceback
        traceback.print_exc()
        run_logger.log_orchestrator(f"Error: {e}", level="ERROR")
        _finalize_session(session_stats, start_time, items_completed, total_requests, run_logger)
        return 1
    finally:
        terminal_ui.ui.stop()
        # Ensure merge queue is properly shut down
        try:
            from pokepoke.merge_queue import get_merge_queue
            merge_queue = get_merge_queue()
            if merge_queue.is_running:
                merge_queue.shutdown(timeout=10.0)
        except Exception as e:
            logger.debug(f"Failed to shutdown merge queue during cleanup: {e}")
        # Clean up signal handlers
        with contextlib.suppress(Exception):
            unregister_shutdown_handlers()

def main() -> int:
    """Main entry point for PokePoke CLI."""
    parser = argparse.ArgumentParser(
        description="PokePoke - Autonomous Beads + Copilot CLI Orchestrator"
    )
    parser.add_argument("--interactive", action="store_true", default=True,
                        help="Interactive mode: prompt for user input (default)")
    parser.add_argument("--autonomous", action="store_true",
                        help="Autonomous mode: automatic decision making")
    parser.add_argument("--continuous", action="store_true",
                        help="Continuous mode: loop through multiple items")
    parser.add_argument("--beta-first", action="store_true",
                        help="Run beta tester at startup before work items")
    parser.add_argument("--agent-name", type=str, default=None,
                        help="Custom agent name instead of auto-generating")
    parser.add_argument("--init", action="store_true",
                        help="Initialize .pokepoke/ directory with sample config")
    parser.add_argument("--max-agents", type=int, default=1, metavar="N",
                        help="Max concurrent work-item agents (default: 1)")
    args = parser.parse_args()

    if args.init:
        from pokepoke.init import init_project
        return 0 if init_project() else 1

    # Autonomous flag overrides interactive
    interactive = not args.autonomous

    from pokepoke.desktop_ui import DesktopUI
    from pokepoke.project_utils import ensure_project_ready
    active_ui: DesktopUI = terminal_ui.ui

    desktop_ui_ref = active_ui if isinstance(active_ui, DesktopUI) else None

    # Run the orchestrator with the selected UI
    def orchestrator_func() -> int:
        if not ensure_project_ready(interactive, desktop_ui_ref):
            return 1
        return run_orchestrator(
            interactive=interactive,
            continuous=args.continuous,
            run_beta_first=args.beta_first,
            agent_name_override=args.agent_name,
            max_parallel_agents=args.max_agents,
        )

    return active_ui.run_with_orchestrator(orchestrator_func)
if __name__ == "__main__":
    sys.exit(main())
