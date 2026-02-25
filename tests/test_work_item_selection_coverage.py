"""Integration-style tests for work_item_selection.py.

These tests exercise real code paths in work_item_selection.py, mocking only
external I/O boundaries (beads CLI calls, user input, shutdown flag).
"""

from unittest.mock import patch


from pokepoke.types import BeadsWorkItem
from pokepoke.work_item_selection import (
    _is_human_required,
    select_work_item,
    interactive_selection,
    autonomous_selection,
    select_multiple_items,
)


def _item(id: str, priority: int = 1, labels: list[str] | None = None,
          assignee: str | None = None) -> BeadsWorkItem:
    return BeadsWorkItem(
        id=id, title=f"Item {id}", status="ready", priority=priority,
        issue_type="task", labels=labels, assignee=assignee,
    )


# ── _is_human_required ──────────────────────────────────────────────

class TestIsHumanRequired:
    def test_no_labels(self):
        assert _is_human_required(_item("a")) is False

    def test_empty_labels(self):
        assert _is_human_required(_item("a", labels=[])) is False

    def test_human_required_label(self):
        assert _is_human_required(_item("a", labels=["human-required"])) is True

    def test_other_labels(self):
        assert _is_human_required(_item("a", labels=["bug", "enhancement"])) is False

    def test_mixed_labels(self):
        assert _is_human_required(_item("a", labels=["bug", "human-required"])) is True


# ── select_work_item ────────────────────────────────────────────────

class TestSelectWorkItem:
    """Tests that exercise the filtering logic in select_work_item."""

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_autonomous_selects_item(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a"), _item("b")]
        mock_hier.return_value = items[0]
        result = select_work_item(items, interactive=False)
        assert result is not None
        assert result.id == "a"
        mock_hier.assert_called_once()

    def test_empty_list_returns_none(self):
        result = select_work_item([], interactive=False)
        assert result is None

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_skip_ids_filters(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a"), _item("b")]
        mock_hier.return_value = items[1]
        result = select_work_item(items, interactive=False, skip_ids={"a"})
        # Should only pass item "b" to autonomous_selection
        assert result is not None
        assert result.id == "b"

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item", return_value=None)
    def test_all_skipped_returns_none(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a")]
        result = select_work_item(items, interactive=False, skip_ids={"a"})
        assert result is None

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_filters_human_required(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a", labels=["human-required"]), _item("b")]
        mock_hier.return_value = _item("b")
        result = select_work_item(items, interactive=False)
        assert result is not None
        assert result.id == "b"

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies")
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_filters_blocked_dependencies(self, mock_hier, mock_assigned, mock_deps):
        mock_deps.side_effect = lambda item_id: item_id == "a"
        items = [_item("a"), _item("b")]
        mock_hier.return_value = _item("b")
        result = select_work_item(items, interactive=False)
        assert result is not None
        assert result.id == "b"

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user")
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item", return_value=None)
    def test_filters_other_agent_assigned(self, mock_hier, mock_assigned, mock_deps):
        mock_assigned.side_effect = lambda item: item.id != "a"
        items = [_item("a", assignee="other-agent"), _item("b")]
        result = select_work_item(items, interactive=False)
        # "a" is filtered, but "b" passes; mock returns None for autonomous
        assert result is None

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("builtins.input", return_value="1")
    def test_interactive_selects_by_number(self, mock_input, mock_assigned, mock_deps):
        items = [_item("a"), _item("b")]
        result = select_work_item(items, interactive=True)
        assert result is not None
        assert result.id == "a"

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    def test_all_human_required_returns_none(self, mock_assigned, mock_deps):
        items = [_item("a", labels=["human-required"])]
        result = select_work_item(items, interactive=False)
        assert result is None


# ── interactive_selection ───────────────────────────────────────────

class TestInteractiveSelection:
    @patch("pokepoke.work_item_selection.is_shutting_down", return_value=False)
    @patch("builtins.input", return_value="2")
    def test_selects_by_number(self, mock_input, mock_shutdown):
        items = [_item("a"), _item("b")]
        result = interactive_selection(items)
        assert result is not None
        assert result.id == "b"

    @patch("pokepoke.work_item_selection.is_shutting_down", return_value=False)
    @patch("builtins.input", return_value="q")
    def test_quit(self, mock_input, mock_shutdown):
        result = interactive_selection([_item("a")])
        assert result is None

    @patch("pokepoke.work_item_selection.is_shutting_down", return_value=False)
    @patch("builtins.input", side_effect=["invalid", "1"])
    def test_invalid_then_valid(self, mock_input, mock_shutdown):
        items = [_item("a")]
        result = interactive_selection(items)
        assert result is not None
        assert result.id == "a"

    @patch("pokepoke.work_item_selection.is_shutting_down", return_value=False)
    @patch("builtins.input", side_effect=["99", "1"])
    def test_out_of_range_then_valid(self, mock_input, mock_shutdown):
        items = [_item("a")]
        result = interactive_selection(items)
        assert result is not None
        assert result.id == "a"

    @patch("pokepoke.work_item_selection.is_shutting_down", return_value=False)
    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_keyboard_interrupt(self, mock_input, mock_shutdown):
        result = interactive_selection([_item("a")])
        assert result is None

    @patch("pokepoke.work_item_selection.is_shutting_down", return_value=True)
    def test_shutdown_returns_none(self, mock_shutdown):
        result = interactive_selection([_item("a")])
        assert result is None


# ── autonomous_selection ────────────────────────────────────────────

class TestAutonomousSelection:
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_selects_item(self, mock_hier):
        items = [_item("a"), _item("b")]
        mock_hier.return_value = items[1]
        result = autonomous_selection(items)
        assert result is not None
        assert result.id == "b"

    @patch("pokepoke.work_item_selection.select_next_hierarchical_item", return_value=None)
    def test_no_selection(self, mock_hier):
        result = autonomous_selection([_item("a")])
        assert result is None


# ── select_multiple_items ───────────────────────────────────────────

class TestSelectMultipleItems:
    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_selects_up_to_count(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a"), _item("b"), _item("c")]
        mock_hier.side_effect = [items[0], items[1]]
        result = select_multiple_items(items, count=2)
        assert len(result) == 2
        assert result[0].id == "a"
        assert result[1].id == "b"

    def test_empty_items(self):
        assert select_multiple_items([], count=3) == []

    def test_zero_count(self):
        assert select_multiple_items([_item("a")], count=0) == []

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_skips_excluded_ids(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a"), _item("b")]
        mock_hier.return_value = _item("b")
        result = select_multiple_items(items, count=2, skip_ids={"a"})
        assert len(result) == 1
        assert result[0].id == "b"

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_skips_claimed_ids(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a"), _item("b")]
        mock_hier.return_value = _item("b")
        result = select_multiple_items(items, count=2, claimed_ids={"a"})
        assert len(result) == 1
        assert result[0].id == "b"

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_filters_human_required(self, mock_hier, mock_assigned, mock_deps):
        items = [_item("a", labels=["human-required"]), _item("b")]
        mock_hier.return_value = _item("b")
        result = select_multiple_items(items, count=2)
        assert len(result) == 1
        assert result[0].id == "b"

    @patch("pokepoke.work_item_selection.has_unmet_blocking_dependencies", return_value=False)
    @patch("pokepoke.work_item_selection.is_assigned_to_current_user", return_value=True)
    @patch("pokepoke.work_item_selection.select_next_hierarchical_item", return_value=None)
    def test_hier_returns_none(self, mock_hier, mock_assigned, mock_deps):
        result = select_multiple_items([_item("a")], count=2)
        assert result == []
