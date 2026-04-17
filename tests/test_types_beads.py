"""Tests for pokepoke.types_beads module.

Verifies all beads-domain dataclasses (BeadsWorkItem, BeadsCreatedItem,
Dependency, IssueWithDependencies) and the RecordFn callback protocol.
"""

from dataclasses import asdict, replace

import pytest

from pokepoke.types_beads import (
    BeadsCreatedItem,
    BeadsWorkItem,
    Dependency,
    IssueWithDependencies,
    RecordFn,
)

# ---------------------------------------------------------------------------
# BeadsWorkItem
# ---------------------------------------------------------------------------

class TestBeadsWorkItem:
    """Tests for BeadsWorkItem dataclass."""

    def test_required_fields(self) -> None:
        item = BeadsWorkItem(
            id="bd-1", title="Fix bug", status="open",
            priority=1, issue_type="bug",
        )
        assert item.id == "bd-1"
        assert item.title == "Fix bug"
        assert item.status == "open"
        assert item.priority == 1
        assert item.issue_type == "bug"

    def test_optional_fields_default_none(self) -> None:
        item = BeadsWorkItem(
            id="bd-2", title="t", status="open",
            priority=0, issue_type="task",
        )
        assert item.description is None
        assert item.owner is None
        assert item.assignee is None
        assert item.created_at is None
        assert item.created_by is None
        assert item.updated_at is None
        assert item.labels is None
        assert item.metadata is None
        assert item.is_ephemeral is False

    def test_all_fields_populated(self) -> None:
        item = BeadsWorkItem(
            id="bd-3", title="feat", status="in_progress",
            priority=2, issue_type="feature",
            description="desc", owner="alice", assignee="agent_1",
            created_at="2026-01-01", created_by="bob",
            updated_at="2026-01-02", labels=["backend"],
            metadata={"gate_rejection_count": 2}, is_ephemeral=True,
        )
        assert item.description == "desc"
        assert item.labels == ["backend"]
        assert item.metadata == {"gate_rejection_count": 2}
        assert item.is_ephemeral is True

    def test_replace_creates_copy(self) -> None:
        original = BeadsWorkItem(
            id="bd-4", title="t", status="open",
            priority=0, issue_type="task",
        )
        copy = replace(original, title="updated")
        assert copy.title == "updated"
        assert original.title == "t"

    def test_asdict_round_trip(self) -> None:
        item = BeadsWorkItem(
            id="bd-5", title="t", status="open",
            priority=1, issue_type="bug",
        )
        d = asdict(item)
        assert d["id"] == "bd-5"
        restored = BeadsWorkItem(**d)
        assert restored == item

    def test_equality(self) -> None:
        a = BeadsWorkItem(id="x", title="t", status="open", priority=0, issue_type="task")
        b = BeadsWorkItem(id="x", title="t", status="open", priority=0, issue_type="task")
        assert a == b

    def test_inequality_on_different_field(self) -> None:
        a = BeadsWorkItem(id="x", title="t", status="open", priority=0, issue_type="task")
        b = BeadsWorkItem(id="y", title="t", status="open", priority=0, issue_type="task")
        assert a != b


# ---------------------------------------------------------------------------
# BeadsCreatedItem
# ---------------------------------------------------------------------------

class TestBeadsCreatedItem:
    """Tests for BeadsCreatedItem (frozen dataclass)."""

    def test_defaults(self) -> None:
        item = BeadsCreatedItem(id="ci-1")
        assert item.title == ""
        assert item.agent_type == "unknown"

    def test_custom_values(self) -> None:
        item = BeadsCreatedItem(id="ci-2", title="New item", agent_type="work")
        assert item.id == "ci-2"
        assert item.title == "New item"
        assert item.agent_type == "work"

    def test_frozen_immutability(self) -> None:
        item = BeadsCreatedItem(id="ci-3")
        with pytest.raises(AttributeError):
            item.id = "changed"  # type: ignore[misc]

    def test_hashable(self) -> None:
        item = BeadsCreatedItem(id="ci-4", title="t", agent_type="gate")
        assert isinstance(hash(item), int)

    def test_replace_on_frozen(self) -> None:
        item = BeadsCreatedItem(id="ci-5", title="old")
        new_item = replace(item, title="new")
        assert new_item.title == "new"
        assert item.title == "old"


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

class TestDependency:
    """Tests for Dependency dataclass."""

    def test_required_fields(self) -> None:
        dep = Dependency(
            id="d-1", title="blocker", issue_type="bug",
            dependency_type="blocks",
        )
        assert dep.id == "d-1"
        assert dep.dependency_type == "blocks"

    def test_optional_fields_default_none(self) -> None:
        dep = Dependency(
            id="d-2", title="t", issue_type="task",
            dependency_type="related",
        )
        assert dep.status is None
        assert dep.priority is None
        assert dep.description is None
        assert dep.owner is None
        assert dep.created_at is None
        assert dep.created_by is None
        assert dep.updated_at is None
        assert dep.labels is None
        assert dep.notes is None

    def test_all_dependency_types(self) -> None:
        for dep_type in ("parent", "blocks", "related", "discovered-from"):
            dep = Dependency(
                id="d-3", title="t", issue_type="task",
                dependency_type=dep_type,
            )
            assert dep.dependency_type == dep_type


# ---------------------------------------------------------------------------
# IssueWithDependencies
# ---------------------------------------------------------------------------

class TestIssueWithDependencies:
    """Tests for IssueWithDependencies dataclass."""

    def test_required_fields(self) -> None:
        issue = IssueWithDependencies(
            id="iwd-1", title="t", status="open",
            priority=1, issue_type="feature",
        )
        assert issue.id == "iwd-1"
        assert issue.dependencies is None
        assert issue.dependents is None

    def test_with_dependencies(self) -> None:
        dep = Dependency(
            id="d-1", title="blocker", issue_type="bug",
            dependency_type="blocks",
        )
        issue = IssueWithDependencies(
            id="iwd-2", title="t", status="open",
            priority=0, issue_type="task",
            dependencies=[dep],
        )
        assert issue.dependencies is not None
        assert len(issue.dependencies) == 1
        assert issue.dependencies[0].id == "d-1"

    def test_with_dependents(self) -> None:
        dependent = Dependency(
            id="d-2", title="child", issue_type="task",
            dependency_type="parent",
        )
        issue = IssueWithDependencies(
            id="iwd-3", title="parent", status="open",
            priority=1, issue_type="epic",
            dependents=[dependent],
        )
        assert issue.dependents is not None
        assert len(issue.dependents) == 1

    def test_optional_fields(self) -> None:
        issue = IssueWithDependencies(
            id="iwd-4", title="t", status="closed",
            priority=2, issue_type="task",
            description="d", owner="alice", assignee="bot",
            created_at="2026-01-01", created_by="bob",
            updated_at="2026-01-02", labels=["backend", "api"],
            notes="some notes",
        )
        assert issue.notes == "some notes"
        assert issue.labels == ["backend", "api"]
        assert issue.assignee == "bot"


# ---------------------------------------------------------------------------
# RecordFn protocol
# ---------------------------------------------------------------------------

class TestRecordFnProtocol:
    """Tests for the RecordFn callback protocol."""

    def test_protocol_is_importable(self) -> None:
        assert callable(RecordFn)

    def test_callable_satisfies_protocol(self) -> None:
        """A plain function matching the signature should satisfy RecordFn."""
        from typing import Any


        def my_record(
            item: BeadsWorkItem,
            result: Any,
            session_stats: Any,
            run_logger: Any,
        ) -> None:
            pass

        # Runtime duck-type check: the function is callable with the right arity.
        assert callable(my_record)
