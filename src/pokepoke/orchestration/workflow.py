"""Workflow management for work item selection and processing."""
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.agents.agent_context import get_agent_name
from pokepoke.agents.agent_runner import run_gate_agent  # re-exported via workflow_helpers
from pokepoke.beads.beads import add_comment, assign_and_sync_item
from pokepoke.config import get_config
from pokepoke.desktop import terminal_ui
from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.models.copilot_sdk import build_prompt_from_work_item
from pokepoke.models.model_selection import get_assignment_for_item, select_model_for_item
from pokepoke.models.sdk_helpers import build_resume_prompt
from pokepoke.orchestration.work_item_selection import select_work_item  # noqa: F401  # re-exported
from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.workflow_helpers import (
    _apply_gate_feedback,
    _extract_agent_stats,
    _fail_result,
    _finalize_item_result,
    _log_commit_status,
    _log_failure,
    _maybe_retry_copilot,
    run_cleanup_with_timeout,
    setup_worktree,
)
from pokepoke.protocols import BeadsClient
from pokepoke.stats.metrics_context import set_current_repo_name, set_current_work_item_id
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult, WorkItemResult
from pokepoke.utils.shutdown import is_shutting_down, register_agent, unregister_agent
from pokepoke.worktrees.worktrees import cleanup_worktree, create_worktree  # noqa: F401 — kept for test patching

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import RunLogger

logger = logging.getLogger(__name__)

_MAX_GATE_CRASH_RETRIES = 3
_MAX_GATE_TIMEOUT_RETRIES = 3
_LOCK_TIMEOUT_PER_AGENT = 120.0

def process_work_item(  # noqa: C901
    item: BeadsWorkItem,
    interactive: bool,
    timeout_hours: float = 0,
    run_beta_test: bool = False,
    run_logger: 'RunLogger | None' = None,
    max_timeout_restarts: int = 3,
    agent_id: str | None = None,
    repo_path: str | None = None,
    beads_client: BeadsClient | None = None,
) -> WorkItemResult:
    """Process a single work item with timeout protection."""
    register_agent()
    _assign = beads_client.assign_and_sync_item if beads_client else assign_and_sync_item
    _comment = beads_client.add_comment if beads_client else add_comment
    _session: WorkItemSession | None = None
    try:
        start_time = time.time()
        timeout_seconds = timeout_hours * 3600
        request_count = 0
        cleanup_agent_runs = 0
        gate_agent_runs = 0
        config = get_config()
        selected_model = select_model_for_item(item)
        _, selected_prompt_template = get_assignment_for_item(item)
        base_agent_id = agent_id or item.id
        backend_provider = config.ai_backend.provider
        worktree_lock_timeout = max(float(config.command_timeout), _LOCK_TIMEOUT_PER_AGENT * max(1, int(config.max_parallel_agents)))

        set_current_work_item_id(item.id)
        repo_name = Path(repo_path).name if repo_path else Path.cwd().name
        set_current_repo_name(repo_name)

        terminal_ui.ui.push_agent_status(base_agent_id, get_agent_name(default="pokepoke"),
            iteration=1, status="running", model=selected_model,
            work_item_id=item.id, work_item_title=item.title, agent_type="work")

        logger.info(f"\n🚀 Processing work item: {item.id} — {item.title}")
        timeout_label = f"{timeout_hours}h" if timeout_hours > 0 else "unlimited"
        logger.info(f"   🤖 Model: {selected_model} | 🧠 Backend: {backend_provider} | ⏱️  Timeout: {timeout_label}\n")

        item_logger = run_logger.start_item_log(item.id, item.title) if run_logger else None

        from pokepoke.beads.beads_management import get_gate_rejection_count
        existing_rejection_count = get_gate_rejection_count(item.id)
        max_gate_rejections = config.max_gate_rejections_per_item
        if existing_rejection_count >= max_gate_rejections:
            logger.error(f"\n\u274c Item {item.id} has {existing_rejection_count} gate rejections (cap: {max_gate_rejections}). Refusing to process.")
            _comment(item.id, f"\u26d4 Refusing to process: {existing_rejection_count} gate rejections (cap: {max_gate_rejections}). Requires manual review.")
            _log_failure(run_logger, item_logger)
            return _fail_result()

        if interactive:
            terminal_ui.ui.stop()
            confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
            terminal_ui.ui.start()
            if confirm and confirm != 'y':
                logger.warning("⏭️  Skipped.")
                _log_failure(run_logger, item_logger)
                return _fail_result()

        logger.info("\n\U0001f512 Claiming work item...")
        if not _assign(item.id):
            logger.error(f"❌ Failed to assign work item {item.id}")
            _log_failure(run_logger, item_logger)
            return _fail_result()
        _session = WorkItemSession(item_id=item.id, agent_name=get_agent_name(default="pokepoke"))
        _session._assigned = True
        worktree_path = setup_worktree(item, lock_timeout=worktree_lock_timeout,
            run_logger=run_logger, item_logger=item_logger, repo_path=repo_path)

        if worktree_path is None:
            logger.error(f"↩️  Returning {item.id} to queue (unassigning due to worktree failure)...")
            _log_failure(run_logger, item_logger)
            return _fail_result()
        _session.worktree_path = str(worktree_path)
        _session._worktree_created = True
        _session._branch_created = True

        pokepoke_root = Path(repo_path) if repo_path else Path.cwd()
        worktree_cwd = str(worktree_path)
        logger.info(f"   Working directory: {worktree_cwd}\n")
        last_feedback = ""
        accumulated_feedback: list[str] = []
        accumulated_stats = AgentStats()
        gate_success = False
        timeout_restart_count = 0
        work_agent_iteration = 1
        copilot_failure_count = 0
        gate_rejection_count = existing_rejection_count
        last_retry_was_gate_feedback = False
        current_work_agent_id = base_agent_id
        resume_session_id: str | None = None
        resume_output_summary: str | None = None
        process_crashed_this_session = False  # Track crashes to skip gate validation
        result = CopilotResult(work_item_id=item.id, success=False,
            error="Session aborted due to application shutdown", attempt_count=0)

        while not is_shutting_down():
            # Check timeout before invoking Copilot
            elapsed = time.time() - start_time
            if timeout_seconds > 0 and elapsed >= timeout_seconds:
                timeout_restart_count += 1
                if timeout_restart_count > max_timeout_restarts:
                    logger.info(f"\n\u23f1\ufe0f  TIMEOUT: Exceeded max restarts ({max_timeout_restarts}), failing {item.id}")
                    _log_failure(run_logger, item_logger, request_count)
                    logger.info(f"\n\u26a0\ufe0f  Preserving worktree for {item.id} (work may be recoverable)")
                    terminal_ui.ui.set_current_agent(None)
                    return _fail_result(request_count=request_count, stats=accumulated_stats,
                                        cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs)
                logger.info(f"\n\u23f1\ufe0f  TIMEOUT: Restarting {item.id} (attempt {timeout_restart_count}/{max_timeout_restarts})")
                start_time = time.time()
                elapsed = 0

            remaining_timeout = (timeout_seconds - elapsed) if timeout_seconds > 0 else None

            # Append feedback if retrying
            if last_feedback:
                if last_retry_was_gate_feedback:
                    logger.info("\n🔄 Restarting Work Agent with feedback...")
                else:
                    logger.info("\n⏱️  Resuming Work Agent after timeout...")
                accumulated_feedback, work_agent_iteration = _apply_gate_feedback(
                    last_feedback, accumulated_feedback, work_agent_iteration)
            terminal_ui.ui.set_current_agent("Work Agent")
            from pokepoke.stats.metrics_context import agent_type_context
            prompt_template = selected_prompt_template or "beads-item"
            is_resume = resume_session_id is not None
            if is_resume:
                work_prompt = build_resume_prompt(
                    item,
                    previous_output_summary=resume_output_summary,
                    retry_feedback=accumulated_feedback or None,
                )
            else:
                work_prompt = build_prompt_from_work_item(
                    item, template_name=prompt_template,
                    retry_feedback=accumulated_feedback or None)
            with agent_type_context("work"):
                is_retry = work_agent_iteration > 1
                if is_retry and not last_retry_was_gate_feedback:
                    # Timeout/crash retry: reuse the existing agent card
                    agent_id = current_work_agent_id
                    resume_in_place = True
                    parent_for_status = None
                else:
                    # First attempt or gate rejection retry: new card
                    agent_id = f"{base_agent_id}-retry-{work_agent_iteration}" if is_retry else base_agent_id
                    current_work_agent_id = agent_id
                    resume_in_place = False
                    parent_for_status = base_agent_id if is_retry else None
                terminal_ui.ui.push_agent_status(agent_id, get_agent_name(default="pokepoke"),
                    iteration=work_agent_iteration, status="running", model=selected_model,
                    parent_agent_id=parent_for_status,
                    work_item_id=item.id, work_item_title=item.title, agent_type="work",
                    agent_prompt=work_prompt, resume_in_place=resume_in_place)

                # Pre-invocation guard: Verify worktree is on expected branch before launching agent
                # Only run if worktree directory actually exists (skip during unit tests with mocked paths)
                from pokepoke.git.git_helpers import run_git as _run_git_check
                from pokepoke.git.git_operations import sanitize_branch_name
                from pokepoke.utils.constants import BRANCH_PREFIX

                if Path(worktree_cwd).exists():
                    sanitized_id = sanitize_branch_name(item.id)
                    expected_branch = f"{BRANCH_PREFIX}{sanitized_id}"

                    try:
                        branch_check = _run_git_check(
                            ["git", "branch", "--show-current"],
                            cwd=worktree_cwd,
                            timeout=10,
                            check=False,
                        )
                        if branch_check.returncode == 0:
                            current_branch = branch_check.stdout.strip()
                            if current_branch != expected_branch:
                                error_msg = (
                                    f"FATAL: Worktree for {item.id} is on wrong branch '{current_branch}' "
                                    f"(expected '{expected_branch}'). Refusing to invoke agent. "
                                    "This prevents committing to the default branch."
                                )
                                logger.error(f"\n❌ {error_msg}")
                                _log_failure(run_logger, item_logger, request_count)
                                terminal_ui.ui.set_current_agent(None)
                                return _fail_result(request_count=request_count, stats=accumulated_stats,
                                                  cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs)
                    except Exception as e:
                        error_msg = f"FATAL: Failed to verify worktree branch: {e}"
                        logger.error(f"\n❌ {error_msg}")
                        _log_failure(run_logger, item_logger, request_count)
                        terminal_ui.ui.set_current_agent(None)
                        return _fail_result(request_count=request_count, stats=accumulated_stats,
                                          cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs)

                with terminal_ui.ui.agent_output_for(agent_id):
                    result = invoke_copilot(
                        item, prompt=work_prompt, timeout=remaining_timeout,
                        item_logger=item_logger, model=selected_model, cwd=worktree_cwd,
                        session_id=resume_session_id, is_resume=is_resume)
            request_count += result.attempt_count

            current_stats = _extract_agent_stats(result)
            if current_stats:
                accumulated_stats.accumulate(current_stats)

            is_process_crash = result.error and (
                "process died" in result.error.lower()
                or "exited unexpectedly" in result.error.lower()
            )
            if is_process_crash:
                process_crashed_this_session = True

            if not result.success:
                copilot_failure_count += 1
                is_timeout_failure = (
                    result.error and ("timeout" in result.error.lower()
                                      or "inactivity" in result.error.lower())
                )
                if is_timeout_failure and result.session_id:
                    resume_session_id = result.session_id
                    resume_output_summary = result.last_output_summary
                    logger.info(f"\n📎 Session state saved for resume (session: {resume_session_id})")
                else:
                    resume_session_id = None
                    resume_output_summary = None

                if is_process_crash:
                    logger.warning(f"\n⚠️  CLI process crashed: {result.error} — gate check will be skipped")

                retry, feedback = _maybe_retry_copilot(
                    result, copilot_failure_count, config.max_copilot_failure_retries, run_logger, item.id)
                if retry:
                    last_feedback = feedback
                    last_retry_was_gate_feedback = False  # Not a gate rejection
                    continue
                break

            _log_commit_status(worktree_cwd)

            # Skip cleanup/gate if agent already closed the beads item (self-merge)
            from pokepoke.beads.reconciliation import is_beads_item_closed
            if is_beads_item_closed(item.id):
                logger.warning("\n✅ Agent already closed beads item — skipping cleanup and gate checks")
                gate_success = True
                break

            cleanup_success, cleanup_runs = run_cleanup_with_timeout(
                item, result, pokepoke_root, start_time, timeout_seconds, timeout_hours, worktree_cwd,
                parent_agent_id=base_agent_id,
            )
            cleanup_agent_runs += cleanup_runs

            if not cleanup_success:
                result.success = False
                _log_failure(run_logger, item_logger, request_count)
                return _fail_result(request_count=request_count, stats=accumulated_stats,
                                    cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs)

            if process_crashed_this_session:
                logger.warning("\n⏭️  Skipping Gate Agent — CLI process crashed, work may be incomplete")
                gate_success = True
                break

            if not config.gate_agent_enabled:
                logger.warning("\n⏭️  Gate Agent disabled via config — skipping verification")
                gate_success = True
                break

            # Run gate agent with crash and timeout retry loops
            gate_crash_attempts = 0
            gate_timeout_attempts = 0
            gate_resume_session_id: str | None = None
            _gate_resume_output: str | None = None
            while gate_crash_attempts < _MAX_GATE_CRASH_RETRIES:
                from pokepoke.git.git_operations import build_handoff_context
                handoff_ctx = build_handoff_context(cwd=worktree_cwd)
                gate_iteration = gate_agent_runs + 1
                gate_agent_id = f"{base_agent_id}-gate-{gate_iteration}"
                gate_is_resume = gate_resume_session_id is not None
                resume_in_place = gate_is_resume
                gate_crashed = False
                gate_timed_out = False
                try:
                    with terminal_ui.ui.agent_output_for(gate_agent_id):
                        if resume_in_place:
                            terminal_ui.ui.push_agent_status(
                                gate_agent_id, "Gate Agent",
                                iteration=gate_iteration, status="running",
                                parent_agent_id=base_agent_id,
                                work_item_id=item.id, work_item_title=item.title,
                                agent_type="gate", resume_in_place=True,
                            )
                        gate_result = run_gate_agent(
                            item, cwd=worktree_cwd, work_model=selected_model,
                            handoff_context=handoff_ctx,
                            agent_id=gate_agent_id, agent_iteration=gate_iteration,
                            parent_agent_id=base_agent_id,
                            item_logger=item_logger,
                            session_id=gate_resume_session_id,
                            is_resume=gate_is_resume,
                        )
                    gate_success = gate_result.success
                    gate_reason = gate_result.reason
                    gate_crashed = gate_result.crashed
                    gate_timed_out = gate_result.is_timeout
                except Exception as e:
                    logger.warning(f"Gate agent raised exception: {e}", exc_info=True)
                    gate_agent_runs += 1
                    gate_crash_attempts += 1
                    terminal_ui.ui.push_agent_status(gate_agent_id, "Gate Agent",
                        iteration=gate_agent_runs, status="failed",
                        parent_agent_id=base_agent_id, work_item_id=item.id, work_item_title=item.title,
                        agent_type="gate")
                    if gate_crash_attempts < _MAX_GATE_CRASH_RETRIES:
                        logger.error(f"\n\u26a0\ufe0f  Gate crashed ({gate_crash_attempts}/{_MAX_GATE_CRASH_RETRIES}): {e}, retrying...")
                        gate_resume_session_id = None
                        _gate_resume_output = None
                        continue
                    logger.error(f"\n❌ Gate Agent crashed {gate_crash_attempts} times — giving up")
                    raise

                gate_agent_runs += 1
                terminal_ui.ui.push_agent_status(gate_agent_id, "Gate Agent",
                    iteration=gate_agent_runs, status="success" if gate_success else "failed",
                    parent_agent_id=base_agent_id, work_item_id=item.id, work_item_title=item.title,
                    agent_type="gate")

                if gate_timed_out:
                    gate_timeout_attempts += 1
                    if gate_timeout_attempts < _MAX_GATE_TIMEOUT_RETRIES:
                        gate_resume_session_id = gate_result.session_id
                        _gate_resume_output = gate_result.last_output_summary
                        logger.info(f"\n\u23f1\ufe0f  Gate timed out ({gate_timeout_attempts}/{_MAX_GATE_TIMEOUT_RETRIES}), {'resuming' if gate_resume_session_id else 'retrying'}...")
                        continue
                    logger.error(f"\n❌ Gate Agent timed out {gate_timeout_attempts} times — giving up")
                    _comment(item.id, f"Gate Agent timed out {gate_timeout_attempts} times:\n{gate_reason}")
                    break

                if gate_crashed:
                    gate_crash_attempts += 1
                    gate_resume_session_id = None
                    _gate_resume_output = None
                    if gate_crash_attempts < _MAX_GATE_CRASH_RETRIES:
                        logger.error(f"\n\u26a0\ufe0f  Gate crashed ({gate_crash_attempts}/{_MAX_GATE_CRASH_RETRIES}): {gate_reason}, retrying...")
                        continue
                    logger.error(f"\n❌ Gate Agent crashed {gate_crash_attempts} times — giving up")
                    _comment(item.id, f"Gate Agent crashed {gate_crash_attempts} times:\n{gate_reason}")
                break  # Not a crash/timeout — exit the gate retry loop

            if gate_success:
                logger.info("\n✅ Gate Agent signed off!")
                break
            elif not gate_crashed and not gate_timed_out:
                # Genuine code rejection — increment persistent counter and check cap
                from pokepoke.beads.beads_management import increment_gate_rejection_count
                new_count = increment_gate_rejection_count(item.id)
                if new_count < 0:
                    gate_rejection_count += 1
                    new_count = gate_rejection_count
                else:
                    gate_rejection_count = new_count
                logger.error(f"\n❌ Gate Agent rejected ({gate_rejection_count}/{max_gate_rejections}): {gate_reason}")
                _comment(item.id, f"Gate Agent Rejection ({gate_rejection_count}/{max_gate_rejections}):\n{gate_reason}")
                if gate_rejection_count >= max_gate_rejections:
                    logger.error(f"\n❌ Exceeded max gate rejections ({gate_rejection_count}/{max_gate_rejections}) for {item.id}")
                    _comment(item.id, f"Abandoned after {gate_rejection_count} gate rejections (cap: {max_gate_rejections}). Last rejection:\n{gate_reason}")
                    result.success = False
                    result.error = f"Exceeded max gate rejections ({max_gate_rejections})"
                    _log_failure(run_logger, item_logger, request_count)
                    break
                # Restart work agent with feedback
                resume_session_id = None
                resume_output_summary = None
                last_feedback = gate_reason
                last_retry_was_gate_feedback = True  # Gate rejection → new card
            else:
                break

        final_result, finalized = _finalize_item_result(
            result, item, worktree_path, selected_model, start_time,
            request_count, accumulated_stats, cleanup_agent_runs, gate_agent_runs,
            gate_success, run_logger, item_logger, base_agent_id, run_beta_test,
            repo_path=repo_path,
        )
        if finalized:
            _session = None  # Finalization succeeded — skip cleanup
        return final_result

    finally:
        set_current_work_item_id(None)
        set_current_repo_name(None)
        if _session is not None and not is_shutting_down():
            _session.cleanup_on_failure()
        unregister_agent()

