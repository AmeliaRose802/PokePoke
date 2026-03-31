"""Tests for pokepoke.agents.agent_child_tracking."""

from types import SimpleNamespace

from pokepoke.agents.agent_child_tracking import ChildAgentTracker


def _agent(status: str, last_log_at: float | None = None,
           last_updated: float | None = None) -> SimpleNamespace:
    """Create a minimal fake AgentRecord."""
    return SimpleNamespace(status=status, last_log_at=last_log_at,
                           last_updated=last_updated)


class TestChildAgentTracker:
    """Unit tests for ChildAgentTracker."""

    def test_add_and_has_active_children(self):
        tracker = ChildAgentTracker()
        agents = {"child-1": _agent("running")}
        tracker.add_child("parent-1", "child-1")
        assert tracker.has_active_children("parent-1", agents)

    def test_has_active_children_false_when_no_children(self):
        tracker = ChildAgentTracker()
        assert not tracker.has_active_children("parent-1", {})

    def test_has_active_children_false_when_child_completed(self):
        tracker = ChildAgentTracker()
        agents = {"child-1": _agent("completed")}
        tracker.add_child("parent-1", "child-1")
        assert not tracker.has_active_children("parent-1", agents)

    def test_has_active_children_with_pending_child(self):
        tracker = ChildAgentTracker()
        agents = {"child-1": _agent("pending")}
        tracker.add_child("parent-1", "child-1")
        assert tracker.has_active_children("parent-1", agents)

    def test_has_active_children_child_not_in_agents(self):
        tracker = ChildAgentTracker()
        tracker.add_child("parent-1", "missing-child")
        assert not tracker.has_active_children("parent-1", {})

    def test_remove_child(self):
        tracker = ChildAgentTracker()
        agents = {"child-1": _agent("running")}
        tracker.add_child("parent-1", "child-1")
        tracker.remove_child("parent-1", "child-1")
        assert not tracker.has_active_children("parent-1", agents)

    def test_remove_child_nonexistent_parent(self):
        tracker = ChildAgentTracker()
        tracker.remove_child("nonexistent", "child-1")  # should not raise

    def test_remove_child_cleans_up_empty_parent(self):
        tracker = ChildAgentTracker()
        tracker.add_child("p", "c")
        tracker.remove_child("p", "c")
        # Internal dict should not keep empty sets
        assert "p" not in tracker._parent_to_children

    def test_remove_parent(self):
        tracker = ChildAgentTracker()
        agents = {"c1": _agent("running"), "c2": _agent("running")}
        tracker.add_child("p", "c1")
        tracker.add_child("p", "c2")
        tracker.remove_parent("p")
        assert not tracker.has_active_children("p", agents)

    def test_remove_parent_nonexistent(self):
        tracker = ChildAgentTracker()
        tracker.remove_parent("nonexistent")  # should not raise

    def test_clear(self):
        tracker = ChildAgentTracker()
        agents = {"c1": _agent("running")}
        tracker.add_child("p1", "c1")
        tracker.add_child("p2", "c1")
        tracker.clear()
        assert not tracker.has_active_children("p1", agents)
        assert not tracker.has_active_children("p2", agents)

    def test_get_active_children(self):
        tracker = ChildAgentTracker()
        agents = {
            "c1": _agent("running"),
            "c2": _agent("completed"),
            "c3": _agent("pending"),
        }
        tracker.add_child("p", "c1")
        tracker.add_child("p", "c2")
        tracker.add_child("p", "c3")
        active = tracker.get_active_children("p", agents)
        assert sorted(active) == ["c1", "c3"]

    def test_get_active_children_no_children(self):
        tracker = ChildAgentTracker()
        assert tracker.get_active_children("p", {}) == []

    def test_get_most_recent_child_activity_none_when_no_children(self):
        tracker = ChildAgentTracker()
        assert tracker.get_most_recent_child_activity("p", {}) is None

    def test_get_most_recent_child_activity_uses_last_log_at(self):
        tracker = ChildAgentTracker()
        agents = {
            "c1": _agent("running", last_log_at=100.0, last_updated=50.0),
            "c2": _agent("running", last_log_at=200.0, last_updated=150.0),
        }
        tracker.add_child("p", "c1")
        tracker.add_child("p", "c2")
        assert tracker.get_most_recent_child_activity("p", agents) == 200.0

    def test_get_most_recent_child_activity_falls_back_to_last_updated(self):
        tracker = ChildAgentTracker()
        agents = {"c1": _agent("running", last_log_at=None, last_updated=99.0)}
        tracker.add_child("p", "c1")
        assert tracker.get_most_recent_child_activity("p", agents) == 99.0

    def test_get_most_recent_child_activity_skips_non_active(self):
        tracker = ChildAgentTracker()
        agents = {
            "c1": _agent("completed", last_log_at=999.0),
            "c2": _agent("running", last_log_at=10.0),
        }
        tracker.add_child("p", "c1")
        tracker.add_child("p", "c2")
        assert tracker.get_most_recent_child_activity("p", agents) == 10.0

    def test_get_most_recent_child_activity_all_inactive(self):
        tracker = ChildAgentTracker()
        agents = {"c1": _agent("completed", last_log_at=999.0)}
        tracker.add_child("p", "c1")
        assert tracker.get_most_recent_child_activity("p", agents) is None

    def test_multiple_parents(self):
        tracker = ChildAgentTracker()
        agents = {"c1": _agent("running"), "c2": _agent("running")}
        tracker.add_child("p1", "c1")
        tracker.add_child("p2", "c2")
        assert tracker.has_active_children("p1", agents)
        assert tracker.has_active_children("p2", agents)
        assert tracker.get_active_children("p1", agents) == ["c1"]
        assert tracker.get_active_children("p2", agents) == ["c2"]

    def test_add_same_child_twice(self):
        tracker = ChildAgentTracker()
        agents = {"c1": _agent("running")}
        tracker.add_child("p", "c1")
        tracker.add_child("p", "c1")
        active = tracker.get_active_children("p", agents)
        assert active == ["c1"]
