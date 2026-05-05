from pathlib import Path
from types import SimpleNamespace

from pokepoke.orchestration.gate_agent_loop import GateOutcomeDetails, _handle_gate_verdict, run_gate_loop
from pokepoke.types_agent import GateAgentResult


class DummyGT:
    def __init__(self):
        self.failed = False
        self.marked = False

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
    ctx = SimpleNamespace(
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
        comment_fn=lambda _id, msg: setattr(ctx, 'last_comment', msg) if False else None,
        defer_fn=lambda _id, msg: setattr(ctx, 'deferred', msg) if False else None,
        resume_session_id=None,
        resume_reason=None,
        resume_output_summary=None,
        resume_feedback=None,
    )
    return ctx


def test_gate_crash_then_success(monkeypatch):
    ctx = make_ctx()
    gt = DummyGT()

    # Avoid real handoff context work
    import pokepoke.git.git_operations as go
    monkeypatch.setattr(go, "build_handoff_context", lambda cwd, work_agent_outcome: "ctx")

    first = GateAgentResult(success=False, reason="crash", crashed=True)
    second = GateAgentResult(success=True, reason="ok")

    calls = [first, second]

    def fake_run_gate_agent(*args, **kwargs):
        return calls.pop(0)

    monkeypatch.setattr("pokepoke.orchestration.gate_agent_loop.run_gate_agent", fake_run_gate_agent)

    res = run_gate_loop(ctx, gt)
    assert res.gate_success is True


def test_handle_gate_infra_failure_no_commits(monkeypatch):
    item = SimpleNamespace(id="item-2")
    ctx = SimpleNamespace(item=item, pokepoke_root=Path.cwd(), gate_rejection_count=0)

    class DummyGT2:
        def mark_success(self, *a, **k):
            self.marked = True

        def mark_failure(self, *a, **k):
            self.failed = True

    gt = DummyGT2()

    import pokepoke.beads.reconciliation as br
    monkeypatch.setattr(br, "worktree_branch_has_commits", lambda _id, _root: False)

    # When there are no commits, infra failure should produce gate_success False
    from pokepoke.orchestration.gate_agent_loop import _handle_gate_infra_failure

    details = GateOutcomeDetails(gate_agent_runs=0, session_id=None, last_output_summary=None, timed_out=False)
    result = _handle_gate_infra_failure(ctx, gt, details)
    assert result.gate_success is False
    assert hasattr(gt, 'failed') and gt.failed is True


def test_handle_gate_verdict_exceeded_defer(monkeypatch):
    item = SimpleNamespace(id="item-3")
    ctx = SimpleNamespace(item=item, pokepoke_root=Path.cwd(), max_gate_rejections=2, gate_rejection_count=0)
    called = {}
    ctx.comment_fn = lambda _id, msg: called.setdefault('comment', msg)
    ctx.defer_fn = lambda _id, msg: called.setdefault('defer', msg)

    class DummyGT3:
        def complete_step(self, *a, **k):
            pass

        def fail_step(self, *a, **k):
            pass

        def gate_rejected_retry(self, *a, **k):
            pass

        def gate_rejected_max(self, *a, **k):
            called['max'] = True

    gt = DummyGT3()

    import pokepoke.beads.beads_management as bm
    monkeypatch.setattr(bm, "increment_gate_rejection_count", lambda _id: 2)

    details = GateOutcomeDetails(gate_agent_runs=1, session_id=None, last_output_summary=None, gate_reason="Some failure")
    res = _handle_gate_verdict(ctx, gt, details)
    assert res.exceeded_max is True
    assert called.get('defer') is not None
    assert called.get('max') is True
