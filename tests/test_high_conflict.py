"""Tests for high-conflict risk label detection."""

from pokepoke.beads_hierarchy import is_high_conflict_risk, HIGH_CONFLICT_LABELS
from pokepoke.types import BeadsWorkItem


def _item(labels: list[str] | None) -> BeadsWorkItem:
    return BeadsWorkItem(
        id="t1",
        title="Test",
        status="open",
        priority=1,
        issue_type="task",
        labels=labels,
    )


def test_high_conflict_detects_primary_label() -> None:
    assert is_high_conflict_risk(_item([HIGH_CONFLICT_LABELS[0]])) is True


def test_high_conflict_detects_alias() -> None:
    assert is_high_conflict_risk(_item([HIGH_CONFLICT_LABELS[1]])) is True


def test_high_conflict_handles_mixed_case() -> None:
    assert is_high_conflict_risk(_item([HIGH_CONFLICT_LABELS[0].upper()])) is True


def test_high_conflict_false_when_absent() -> None:
    assert is_high_conflict_risk(_item(["backend", "urgent"])) is False
