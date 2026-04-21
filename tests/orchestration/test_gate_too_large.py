from pathlib import Path
from types import SimpleNamespace

from pokepoke.orchestration.gate_agent_loop import _handle_gate_verdict


def test_gate_triggers_decomposition_on_too_large(monkeypatch):
    # Prepare a minimal context and dummy GateStepTracker
    item = SimpleNamespace(id="item-1", title="Test", description="Desc", labels=[])
    ctx = SimpleNamespace(
        item=item,
        pokepoke_root=Path.cwd(),
        max_gate_rejections=5,
        gate_rejection_count=0,
    )
    # Provide required callbacks used by the handler
    ctx.comment_fn = lambda _id, msg: setattr(ctx, 'last_comment', msg)
    ctx.defer_fn = lambda _id, msg: setattr(ctx, 'deferred', msg)

    class DummyGT:
        def __init__(self):
            self.max_called = False

        def complete_step(self, *a, **k):
            pass

        def fail_step(self, *a, **k):
            pass

        def gate_rejected_max(self, count):
            self.max_called = True

        def gate_rejected_retry(self, *a, **k):
            pass

    gt = DummyGT()

    # Monkeypatch beads increment function to return a known rejection count
    import pokepoke.beads.beads_management as bm

    monkeypatch.setattr(bm, "increment_gate_rejection_count", lambda _id: 3)

    # Patch decomposition agent to record that it was invoked and return success
    import pokepoke.agents.decomposition_agent as da

    class FakeDecompResult:
        def __init__(self):
            self.success = True
            self.parent_id = item.id
            self.child_ids = ["child-1"]
            self.reason = "ok"

    called = {}

    def fake_run_decomposition(itm, failure_count, too_large_context=None):
        called['invoked'] = True
        assert itm.id == item.id
        assert failure_count == 3
        assert too_large_context is not None
        return FakeDecompResult()

    monkeypatch.setattr(da, "run_decomposition", fake_run_decomposition)

    # Invoke handler with a gate_reason containing 'too_large'
    res = _handle_gate_verdict(ctx, gt, "too_large: scope exceeded", gate_agent_runs=1)

    assert res.exceeded_max is True
    assert called.get('invoked', False) is True
    assert gt.max_called is True


def test_handle_gate_infra_failure_accepts_when_commits(monkeypatch):
    # Prepare context
    item = SimpleNamespace(id="item-2")
    ctx = SimpleNamespace(item=item, pokepoke_root=Path.cwd(), gate_rejection_count=0)
    ctx.comment_fn = lambda _id, msg: setattr(ctx, 'last_comment', msg)

    class DummyGT:
        def mark_success(self, *a, **k):
            self.marked = True

        def mark_failure(self, *a, **k):
            self.failed = True

    gt = DummyGT()

    # Patch worktree_branch_has_commits to return True
    import pokepoke.beads.reconciliation as br

    monkeypatch.setattr(br, "worktree_branch_has_commits", lambda _id, _root: True)

    from pokepoke.orchestration.gate_agent_loop import _handle_gate_infra_failure

    result = _handle_gate_infra_failure(ctx, gt, timed_out=True, gate_agent_runs=0)
    assert result.gate_success is True
    assert hasattr(gt, 'marked') and gt.marked is True


def test_handle_gate_verdict_rejection_triggers_retry(monkeypatch):
    # Prepare context
    item = SimpleNamespace(id="item-3")
    ctx = SimpleNamespace(item=item, pokepoke_root=Path.cwd(), max_gate_rejections=5, gate_rejection_count=0)
    ctx.comment_fn = lambda _id, msg: setattr(ctx, 'last_comment', msg)
    ctx.defer_fn = lambda _id, msg: setattr(ctx, 'deferred', msg)

    class DummyGT:
        def complete_step(self, *a, **k):
            pass

        def fail_step(self, *a, **k):
            pass

        def gate_rejected_retry(self, count, reason):
            self.retry_info = (count, reason)

        def gate_rejected_max(self, *a, **k):
            self.max_called = True

    gt = DummyGT()

    # Patch increment to return 1
    import pokepoke.beads.beads_management as bm
    monkeypatch.setattr(bm, "increment_gate_rejection_count", lambda _id: 1)

    res = _handle_gate_verdict(ctx, gt, "Bad code", gate_agent_runs=1)
    assert res.feedback == "Bad code"
    assert res.exceeded_max is False
    assert hasattr(gt, 'retry_info') and gt.retry_info[0] == 1
