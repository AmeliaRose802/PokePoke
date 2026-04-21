from pathlib import Path
from types import SimpleNamespace

from pokepoke.orchestration.gate_agent_loop import GateLoopContext, run_gate_loop
from pokepoke.types_agent import GateAgentResult


class DummyGT:
    def begin_step(self, *a, **k):
        pass

    def mark_success(self, *a, **k):
        self.marked = True

    def mark_failure(self, *a, **k):
        self.failed = True

    def complete_step(self, *a, **k):
        pass

    def fail_step(self, *a, **k):
        pass

    def gate_rejected_max(self, *a, **k):
        pass

    def gate_rejected_retry(self, *a, **k):
        pass

    def start_work(self, *a, **k):
        pass

    def work_done(self, *a, **k):
        pass

    def cleanup_done(self, *a, **k):
        pass

    def finish_run(self, *a, **k):
        pass


def make_ctx():
    item = SimpleNamespace(id="item-x", title="T")
    result = SimpleNamespace(work_agent_outcome=None)
    ctx = GateLoopContext(
        item=item,
        result=result,
        worktree_cwd=str(Path.cwd()),
        pokepoke_root=Path.cwd(),
        selected_model="m",
        base_agent_id="base",
        max_gate_rejections=3,
        gate_rejection_count=0,
        gate_agent_runs=0,
        item_logger=None,
        comment_fn=lambda _id, msg: None,
        defer_fn=lambda _id, msg: None,
    )
    return ctx


def test_run_gate_loop_success(monkeypatch):
    ctx = make_ctx()
    gt = DummyGT()

    # Patch run_gate_agent to return immediate success
    def fake_run_gate_agent(*args, **kwargs):
        return GateAgentResult(success=True, reason="ok")

    monkeypatch.setattr("pokepoke.orchestration.gate_agent_loop.run_gate_agent", fake_run_gate_agent)

    result = run_gate_loop(ctx, gt)
    assert result.gate_success is True


def test_run_gate_loop_timeout_then_success(monkeypatch):
    ctx = make_ctx()
    gt = DummyGT()

    # Patch build_handoff_context (imported inside loop) to avoid side-effects
    import pokepoke.git.git_operations as go

    monkeypatch.setattr(go, "build_handoff_context", lambda cwd, work_agent_outcome: "ctx")

    first = GateAgentResult(success=False, reason="timeout", crashed=False, is_timeout=True, session_id="s1")
    second = GateAgentResult(success=True, reason="ok")

    calls = [first, second]

    def fake_run_gate_agent(*args, **kwargs):
        return calls.pop(0)

    monkeypatch.setattr("pokepoke.orchestration.gate_agent_loop.run_gate_agent", fake_run_gate_agent)

    result = run_gate_loop(ctx, gt)
    assert result.gate_success is True
