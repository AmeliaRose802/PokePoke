import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokepoke import orchestrator, parallel, workflow
from pokepoke.types import (
    AgentStats,
    BeadsStats,
    BeadsWorkItem,
    CopilotResult,
    SessionStats,
    WorkItemResult,
)


def _make_item(item_id: str = "task-1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title=f"Title for {item_id}",
        status="open",
        priority=1,
        issue_type="task",
        description="Work item description",
        labels=[],
    )


class _DummyUI:
    def __init__(self) -> None:
        self._is_running = True
        self.agent_events: list[tuple] = []

    def set_session_end_time(self, *_args, **_kwargs) -> None:
        pass

    def set_session_start_time(self, *_args, **_kwargs) -> None:
        pass

    def set_logs_dir(self, *_args, **_kwargs) -> None:
        pass

    def update_header(self, *_args, **_kwargs) -> None:
        pass

    def update_stats(self, *_args, **_kwargs) -> None:
        pass

    def stop_and_capture(self, *_args, **_kwargs) -> None:
        self._is_running = False

    def stop(self, *_args, **_kwargs) -> None:
        self._is_running = False

    def start(self, *_args, **_kwargs) -> None:
        self._is_running = True

    def push_agent_status(self, *args, **kwargs) -> None:
        self.agent_events.append((args, kwargs))

    def agent_output_for(self, *_args, **_kwargs):
        return contextlib.nullcontext()

    def agent_output(self, *_args, **_kwargs):
        return contextlib.nullcontext()

    def set_current_agent(self, *_args, **_kwargs) -> None:
        pass

    def log_orchestrator(self, *_args, **_kwargs) -> None:
        pass

    def push_agent_tokens(self, *_args, **_kwargs) -> None:
        pass

    def set_style(self, *_args, **_kwargs) -> None:
        pass

    def is_agent_paused(self, *_args, **_kwargs) -> bool:
        return False


@pytest.fixture(autouse=True)
def fake_ui(monkeypatch: pytest.MonkeyPatch):
    from pokepoke import terminal_ui

    dummy = _DummyUI()
    monkeypatch.setattr(terminal_ui, "ui", dummy)
    monkeypatch.setattr(terminal_ui, "set_terminal_banner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(terminal_ui, "clear_terminal_banner", lambda: None)
    return dummy


@pytest.fixture(autouse=True)
def shutdown_controls(monkeypatch: pytest.MonkeyPatch):
    from pokepoke import shutdown

    shutdown.reset()
    monkeypatch.setattr(shutdown, "is_shutting_down", lambda: False)
    monkeypatch.setattr(shutdown, "should_stop_after_current", lambda: False)
    monkeypatch.setattr(shutdown, "cancel_stop_after_current", lambda: None)
    monkeypatch.setattr(shutdown, "register_agent", lambda: None)
    monkeypatch.setattr(shutdown, "unregister_agent", lambda: None)
    monkeypatch.setattr(shutdown, "set_executor", lambda _executor: None)


@pytest.fixture(autouse=True)
def agent_context_controls(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("pokepoke.agent_context.get_agent_name", lambda default="pokepoke": "base-agent")
    monkeypatch.setattr("pokepoke.agent_context.set_agent_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.agent_context.clear_agent_name", lambda: None)


class WorkflowHarness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.assigned: list[str] = []
        self.created_paths: list[Path] = []
        self.cleaned: list[tuple[str, bool]] = []
        self.copilot_results: list[CopilotResult] = []
        self.copilot_calls: list[str] = []
        self.gate_results: list[tuple[bool, str, AgentStats | None]] = []
        self.cleanup_sequences: list[tuple[bool, int]] = []
        self.uncommitted_sequence: list[bool] = []
        self.finalized: list[str] = []
        self.comments: list[tuple[str, str]] = []
        self.unassigned: list[str] = []
        self.beta_runs: list[str] = []
        self.assign_should_succeed = True
        self.finalize_success = True

        config = SimpleNamespace(
            ai_backend=SimpleNamespace(provider="test-backend"),
            command_timeout=60,
            max_parallel_agents=2,
            gate_agent_enabled=True,
        )
        monkeypatch.setattr(workflow, "get_config", lambda: config)

        monkeypatch.setattr(workflow, "assign_and_sync_item", self._assign_and_sync)
        monkeypatch.setattr(workflow, "create_worktree", self._create_worktree)
        monkeypatch.setattr(workflow, "cleanup_worktree", self._cleanup_worktree)
        monkeypatch.setattr(workflow, "invoke_copilot", self._invoke_copilot)
        monkeypatch.setattr(workflow, "run_gate_agent", self._run_gate_agent)
        monkeypatch.setattr(workflow, "run_cleanup_loop", self._run_cleanup_loop)
        monkeypatch.setattr(workflow, "has_uncommitted_changes", self._has_uncommitted)
        monkeypatch.setattr(workflow, "has_commits_ahead", lambda **_kwargs: 0)
        monkeypatch.setattr(workflow, "finalize_work_item", self._finalize_work_item)
        monkeypatch.setattr(workflow, "unassign_with_retry", self._unassign)
        monkeypatch.setattr(workflow, "add_comment", self._add_comment)
        monkeypatch.setattr(workflow, "build_prompt_from_work_item", lambda *_args, **_kwargs: "prompt")
        monkeypatch.setattr(workflow, "select_model_for_item", lambda *_args, **_kwargs: "test-model")
        monkeypatch.setattr(workflow, "get_assignment_for_item", lambda *_args, **_kwargs: ("work", "beads-item"))
        monkeypatch.setattr(workflow, "calculate_cost", lambda *_args, **_kwargs: 0.0)
        monkeypatch.setattr(workflow, "run_beta_tester", self._run_beta)
        monkeypatch.setattr("pokepoke.git_operations.build_handoff_context", lambda **_kwargs: {"context": "noop"})
        monkeypatch.setattr(workflow, "set_terminal_banner", lambda *_args, **_kwargs: None)

    def _assign_and_sync(self, item_id: str) -> bool:
        self.assigned.append(item_id)
        return self.assign_should_succeed

    def _create_worktree(self, item_id: str, **_kwargs) -> Path:
        path = self.tmp_path / f"worktree-{item_id}"
        path.mkdir(parents=True, exist_ok=True)
        self.created_paths.append(path)
        return path

    def _cleanup_worktree(self, item_id: str, *, force: bool) -> None:
        self.cleaned.append((item_id, force))

    def _invoke_copilot(self, *_args, **_kwargs) -> CopilotResult:
        if not self.copilot_results:
            raise AssertionError("No CopilotResult queued for test")
        result = self.copilot_results.pop(0)
        self.copilot_calls.append(result.work_item_id)
        return result

    def _run_gate_agent(
        self,
        item,
        **_kwargs,
    ) -> tuple[bool, str, AgentStats | None]:
        if self.gate_results:
            return self.gate_results.pop(0)
        return True, "ok", None

    def _run_cleanup_loop(self, *_args, **_kwargs) -> tuple[bool, int]:
        if self.cleanup_sequences:
            return self.cleanup_sequences.pop(0)
        return True, 0

    def _has_uncommitted(self, **_kwargs) -> bool:
        if self.uncommitted_sequence:
            return self.uncommitted_sequence.pop(0)
        return False

    def _finalize_work_item(self, item, _worktree_path, **_kwargs) -> bool:
        self.finalized.append(item.id)
        return self.finalize_success

    def _unassign(self, item_id: str) -> None:
        self.unassigned.append(item_id)

    def _add_comment(self, item_id: str, message: str) -> None:
        self.comments.append((item_id, message))

    def _run_beta(self, *args, **kwargs):
        self.beta_runs.append("beta")
        return AgentStats()


@pytest.fixture
def workflow_harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> WorkflowHarness:
    return WorkflowHarness(monkeypatch, tmp_path)


def test_process_work_item_successful_run(workflow_harness: WorkflowHarness):
    item = _make_item("work-123")
    workflow_harness.copilot_results.append(
        CopilotResult(
            work_item_id=item.id,
            success=True,
            output="done",
            attempt_count=1,
            stats=AgentStats(input_tokens=10, output_tokens=5),
        )
    )
    workflow_harness.gate_results.append((True, "Looks good", AgentStats()))

    result = workflow.process_work_item(item, interactive=False, run_logger=None, run_beta_test=False)

    assert result.success is True
    assert result.request_count == 1
    assert result.gate_agent_runs == 1
    assert workflow_harness.assigned == ["work-123"]
    assert workflow_harness.finalized == ["work-123"]
    assert workflow_harness.cleaned == []


def test_process_work_item_gate_rejection_retries_with_feedback(workflow_harness: WorkflowHarness):
    item = _make_item("work-456")
    workflow_harness.uncommitted_sequence = [True, True, False]
    workflow_harness.cleanup_sequences = [(True, 2)]
    workflow_harness.copilot_results.extend(
        [
            CopilotResult(
                work_item_id=item.id,
                success=True,
                output="attempt-1",
                attempt_count=1,
                stats=AgentStats(input_tokens=4, output_tokens=2),
            ),
            CopilotResult(
                work_item_id=item.id,
                success=True,
                output="attempt-2",
                attempt_count=1,
                stats=AgentStats(input_tokens=3, output_tokens=1),
            ),
        ]
    )
    workflow_harness.gate_results.extend(
        [
            (False, "Needs additional tests", None),
            (True, "Ship it", None),
        ]
    )

    result = workflow.process_work_item(item, interactive=False, run_logger=None, run_beta_test=False)

    assert result.success is True
    assert result.request_count == 2
    assert result.cleanup_agent_runs == 2
    assert result.gate_agent_runs == 2
    assert workflow_harness.comments == [("work-456", "Gate Agent Rejection:\nNeeds additional tests")]
    assert "**PREVIOUS GATE AGENT FEEDBACK:**" in (item.description or "")
    assert workflow_harness.copilot_calls == ["work-456", "work-456"]


class _DummyRunLogger:
    def __init__(self, base_dir: Path) -> None:
        self._run_dir = base_dir / "orchestrator-run"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self.logs: list[str] = []
        self.finalized: tuple[int, int] | None = None

    def get_run_id(self) -> str:
        return "dummy-run"

    def get_run_dir(self) -> Path:
        return self._run_dir

    def log_orchestrator(self, message: str, level: str = "INFO") -> None:
        self.logs.append(f"[{level}] {message}")

    def finalize(self, items_completed: int, total_requests: int, *_args) -> None:
        self.finalized = (items_completed, total_requests)

    def start_item_log(self, *_args, **_kwargs):
        class _ItemLogger:
            def log_summary(self, *_a, **_k) -> None:
                pass

        return _ItemLogger()


class _NoOpMergeQueue:
    is_running = False

    def shutdown(self, *_args, **_kwargs) -> None:
        pass


def test_run_orchestrator_processes_single_item(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    item = _make_item("orch-1")
    result = WorkItemResult(success=True, request_count=2, stats=AgentStats())
    dummy_logger = _DummyRunLogger(tmp_path)

    monkeypatch.setattr("pokepoke.agent_names.initialize_agent_name", lambda **_kwargs: "AgentZero")
    monkeypatch.setattr("pokepoke.agent_context.set_agent_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "get_agent_name", lambda default="pokepoke": "AgentZero")
    monkeypatch.setattr(orchestrator, "load_config", lambda: SimpleNamespace(max_parallel_agents=1))
    monkeypatch.setattr(orchestrator, "get_ready_work_items", lambda: [item])
    monkeypatch.setattr(orchestrator, "select_work_item", lambda *_args, **_kwargs: item)
    monkeypatch.setattr(orchestrator, "process_work_item", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(orchestrator, "check_and_commit_main_repo", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(orchestrator, "get_beads_stats", lambda: BeadsStats())
    monkeypatch.setattr(orchestrator, "record_completion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "append_model_history_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "run_periodic_maintenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "increment_items_completed", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr("pokepoke.beads_item_stats_store.record_item_completed", lambda *_args, **_kwargs: {"total_created": 1, "total_completed": 1})
    monkeypatch.setattr("pokepoke.beads_item_stats_store.get_summary", lambda: {"total_created": 1, "total_completed": 0})
    monkeypatch.setattr("pokepoke.beads_item_stats_backfill.backfill_from_beads_db", lambda **_kwargs: {"backfilled": 0})
    monkeypatch.setattr("pokepoke.beads.retry_failed_unassigns", lambda **_kwargs: 0)
    monkeypatch.setattr("pokepoke.beads.get_failed_unassign_count", lambda: 0)
    monkeypatch.setattr("pokepoke.signal_handlers.register_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.signal_handlers.unregister_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.merge_queue.get_merge_queue", lambda: _NoOpMergeQueue())
    monkeypatch.setattr(orchestrator.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "RunLogger", lambda: dummy_logger)

    exit_code = orchestrator.run_orchestrator(interactive=False, continuous=False, max_parallel_agents=1)

    assert exit_code == 0
    assert dummy_logger.finalized == (1, 2)


def test_run_orchestrator_failure_returns_non_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    item = _make_item("orch-fail")
    result = WorkItemResult(success=False, request_count=0, stats=AgentStats())
    dummy_logger = _DummyRunLogger(tmp_path)

    monkeypatch.setattr("pokepoke.agent_names.initialize_agent_name", lambda **_kwargs: "AgentZero")
    monkeypatch.setattr("pokepoke.agent_context.set_agent_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "get_agent_name", lambda default="pokepoke": "AgentZero")
    monkeypatch.setattr(orchestrator, "load_config", lambda: SimpleNamespace(max_parallel_agents=1))
    monkeypatch.setattr(orchestrator, "get_ready_work_items", lambda: [item])
    monkeypatch.setattr(orchestrator, "select_work_item", lambda *_args, **_kwargs: item)
    monkeypatch.setattr(orchestrator, "process_work_item", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(orchestrator, "check_and_commit_main_repo", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(orchestrator, "get_beads_stats", lambda: BeadsStats())
    monkeypatch.setattr(orchestrator, "record_completion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "append_model_history_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "run_periodic_maintenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "increment_items_completed", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("pokepoke.beads_item_stats_store.record_item_completed", lambda *_args, **_kwargs: {"total_created": 0, "total_completed": 0})
    monkeypatch.setattr("pokepoke.beads_item_stats_store.get_summary", lambda: {"total_created": 0, "total_completed": 0})
    monkeypatch.setattr("pokepoke.beads_item_stats_backfill.backfill_from_beads_db", lambda **_kwargs: {"backfilled": 0})
    monkeypatch.setattr("pokepoke.beads.retry_failed_unassigns", lambda **_kwargs: 0)
    monkeypatch.setattr("pokepoke.beads.get_failed_unassign_count", lambda: 0)
    monkeypatch.setattr("pokepoke.signal_handlers.register_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.signal_handlers.unregister_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.merge_queue.get_merge_queue", lambda: _NoOpMergeQueue())
    monkeypatch.setattr(orchestrator.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "RunLogger", lambda: dummy_logger)

    exit_code = orchestrator.run_orchestrator(interactive=False, continuous=False, max_parallel_agents=1)

    assert exit_code == 1
    assert dummy_logger.finalized == (0, 0)


def test_run_orchestrator_parallel_mode_invokes_parallel_loop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dummy_logger = _DummyRunLogger(tmp_path)
    parallel_calls: list[int] = []

    monkeypatch.setattr("pokepoke.agent_names.initialize_agent_name", lambda **_kwargs: "AgentZero")
    monkeypatch.setattr("pokepoke.agent_context.set_agent_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "get_agent_name", lambda default="pokepoke": "AgentZero")
    monkeypatch.setattr(orchestrator, "load_config", lambda: SimpleNamespace(max_parallel_agents=2))
    monkeypatch.setattr(orchestrator, "get_ready_work_items", lambda: [])
    monkeypatch.setattr(orchestrator, "select_work_item", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "process_work_item", lambda *_args, **_kwargs: WorkItemResult(success=True, request_count=0))
    monkeypatch.setattr(orchestrator, "check_and_commit_main_repo", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(orchestrator, "get_beads_stats", lambda: BeadsStats())
    monkeypatch.setattr(orchestrator, "record_completion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "append_model_history_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "run_periodic_maintenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "increment_items_completed", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr("pokepoke.beads_item_stats_store.record_item_completed", lambda *_args, **_kwargs: {"total_created": 0, "total_completed": 0})
    monkeypatch.setattr("pokepoke.beads_item_stats_store.get_summary", lambda: {"total_created": 0, "total_completed": 0})
    monkeypatch.setattr("pokepoke.beads_item_stats_backfill.backfill_from_beads_db", lambda **_kwargs: {"backfilled": 0})
    monkeypatch.setattr("pokepoke.beads.retry_failed_unassigns", lambda **_kwargs: 0)
    monkeypatch.setattr("pokepoke.beads.get_failed_unassign_count", lambda: 0)
    monkeypatch.setattr("pokepoke.signal_handlers.register_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.signal_handlers.unregister_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.merge_queue.get_merge_queue", lambda: _NoOpMergeQueue())
    monkeypatch.setattr(orchestrator.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "RunLogger", lambda: dummy_logger)

    def fake_parallel_loop(**kwargs):
        parallel_calls.append(kwargs["effective_parallel"])
        return 0

    monkeypatch.setattr(orchestrator, "run_parallel_loop", fake_parallel_loop)

    exit_code = orchestrator.run_orchestrator(interactive=False, continuous=True, max_parallel_agents=3)

    assert exit_code == 0
    assert parallel_calls == [3]


def test_run_orchestrator_honors_stop_after_current(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    item = _make_item("stop-1")
    result = WorkItemResult(success=True, request_count=1, stats=AgentStats())
    dummy_logger = _DummyRunLogger(tmp_path)
    stop_checks: list[bool] = []

    monkeypatch.setattr("pokepoke.agent_names.initialize_agent_name", lambda **_kwargs: "AgentZero")
    monkeypatch.setattr("pokepoke.agent_context.set_agent_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "get_agent_name", lambda default="pokepoke": "AgentZero")
    monkeypatch.setattr(orchestrator, "load_config", lambda: SimpleNamespace(max_parallel_agents=1))
    monkeypatch.setattr(orchestrator, "get_ready_work_items", lambda: [item])
    monkeypatch.setattr(orchestrator, "select_work_item", lambda *_args, **_kwargs: item)
    monkeypatch.setattr(orchestrator, "process_work_item", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(orchestrator, "check_and_commit_main_repo", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(orchestrator, "get_beads_stats", lambda: BeadsStats())
    monkeypatch.setattr(orchestrator, "record_completion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "append_model_history_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "run_periodic_maintenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "increment_items_completed", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr("pokepoke.beads_item_stats_store.record_item_completed", lambda *_args, **_kwargs: {"total_created": 1, "total_completed": 1})
    monkeypatch.setattr("pokepoke.beads_item_stats_store.get_summary", lambda: {"total_created": 1, "total_completed": 0})
    monkeypatch.setattr("pokepoke.beads_item_stats_backfill.backfill_from_beads_db", lambda **_kwargs: {"backfilled": 0})
    monkeypatch.setattr("pokepoke.beads.retry_failed_unassigns", lambda **_kwargs: 0)
    monkeypatch.setattr("pokepoke.beads.get_failed_unassign_count", lambda: 0)
    monkeypatch.setattr("pokepoke.signal_handlers.register_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.signal_handlers.unregister_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.merge_queue.get_merge_queue", lambda: _NoOpMergeQueue())
    monkeypatch.setattr(orchestrator.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "RunLogger", lambda: dummy_logger)

    def fake_should_stop():
        stop_checks.append(True)
        return True

    monkeypatch.setattr("pokepoke.shutdown.should_stop_after_current", fake_should_stop)
    monkeypatch.setattr("pokepoke.shutdown.cancel_stop_after_current", lambda: stop_checks.append(False))

    exit_code = orchestrator.run_orchestrator(interactive=False, continuous=True, max_parallel_agents=1)

    assert exit_code == 0
    assert stop_checks == [True, False]


def test_run_orchestrator_runs_beta_first(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    item = _make_item("beta-1")
    result = WorkItemResult(success=True, request_count=1, stats=AgentStats())
    dummy_logger = _DummyRunLogger(tmp_path)
    beta_calls: list[int] = []

    monkeypatch.setattr("pokepoke.agent_names.initialize_agent_name", lambda **_kwargs: "AgentZero")
    monkeypatch.setattr("pokepoke.agent_context.set_agent_name", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "get_agent_name", lambda default="pokepoke": "AgentZero")
    monkeypatch.setattr(orchestrator, "load_config", lambda: SimpleNamespace(max_parallel_agents=1))
    monkeypatch.setattr(orchestrator, "get_ready_work_items", lambda: [item])
    monkeypatch.setattr(orchestrator, "select_work_item", lambda *_args, **_kwargs: item)
    monkeypatch.setattr(orchestrator, "process_work_item", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(orchestrator, "check_and_commit_main_repo", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(orchestrator, "get_beads_stats", lambda: BeadsStats())
    monkeypatch.setattr(orchestrator, "record_completion", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "append_model_history_entry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "run_periodic_maintenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "increment_items_completed", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr("pokepoke.beads_item_stats_store.record_item_completed", lambda *_args, **_kwargs: {"total_created": 1, "total_completed": 1})
    monkeypatch.setattr("pokepoke.beads_item_stats_store.get_summary", lambda: {"total_created": 1, "total_completed": 0})
    monkeypatch.setattr("pokepoke.beads_item_stats_backfill.backfill_from_beads_db", lambda **_kwargs: {"backfilled": 0})
    monkeypatch.setattr("pokepoke.beads.retry_failed_unassigns", lambda **_kwargs: 0)
    monkeypatch.setattr("pokepoke.beads.get_failed_unassign_count", lambda: 0)
    monkeypatch.setattr("pokepoke.signal_handlers.register_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.signal_handlers.unregister_shutdown_handlers", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("pokepoke.merge_queue.get_merge_queue", lambda: _NoOpMergeQueue())
    monkeypatch.setattr(orchestrator.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestrator, "RunLogger", lambda: dummy_logger)
    def fake_beta(**_kwargs):
        beta_calls.append(1)
        return AgentStats()

    monkeypatch.setattr("pokepoke.agent_runner.run_beta_tester", fake_beta)

    exit_code = orchestrator.run_orchestrator(interactive=False, continuous=False, run_beta_first=True, max_parallel_agents=1)

    assert exit_code == 0
    assert beta_calls == [1]


def test_run_parallel_loop_handles_success_and_failures(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    items = [_make_item("ok-1"), _make_item("fail-claim"), _make_item("crash")]
    available = list(items)
    recorded: list[tuple[str, bool]] = []
    finalized: list[tuple[int, int]] = []

    def fake_ready():
        return list(available)

    def fake_select(ready_items, count, skip_ids=None, claimed_ids=None):
        skip_ids = skip_ids or set()
        claimed_ids = claimed_ids or set()
        selected = []
        for item in ready_items:
            if len(selected) >= count:
                break
            if item.id in skip_ids or item.id in claimed_ids:
                continue
            selected.append(item)
        for sel in selected:
            if sel in available:
                available.remove(sel)
        return selected

    def fake_process(item, **_kwargs):
        if item.id == "crash":
            raise RuntimeError("boom")
        if item.id == "fail-claim":
            return WorkItemResult(success=False, request_count=0)
        return WorkItemResult(success=True, request_count=3)

    def record_fn(item, result, *_args):
        recorded.append((item.id, result.success))

    def finalize_fn(session_stats, _start_time, _items_completed, total_requests, _run_logger):
        finalized.append((session_stats.items_completed, total_requests))

    monkeypatch.setattr(parallel, "get_ready_work_items", fake_ready)
    monkeypatch.setattr(parallel, "select_multiple_items", fake_select)
    monkeypatch.setattr(parallel, "is_item_claimable", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(parallel, "process_work_item", fake_process)
    monkeypatch.setattr(parallel, "check_and_commit_main_repo", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(parallel, "_get_dynamic_max_agents", lambda: 3)
    monkeypatch.setattr(parallel.time, "sleep", lambda *_args, **_kwargs: None)

    stats = SessionStats(agent_stats=AgentStats())
    dummy_logger = _DummyRunLogger(tmp_path)

    exit_code = parallel.run_parallel_loop(
        effective_parallel=2,
        mode_name="Autonomous",
        main_repo_path=Path("."),
        failed_claim_ids=set(),
        session_stats=stats,
        start_time=0.0,
        run_logger=dummy_logger,
        continuous=False,
        record_fn=record_fn,
        finalize_fn=finalize_fn,
        cli_override=False,
    )

    assert exit_code == 0
    assert ("ok-1", True) in recorded
    assert ("fail-claim", False) in recorded
    assert ("crash", False) in recorded
    assert finalized, "finalize_fn should be called once work completes"
