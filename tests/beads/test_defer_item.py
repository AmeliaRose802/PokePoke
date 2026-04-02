"""Tests for defer_item in beads_management."""

import subprocess
from unittest.mock import Mock, patch

from pokepoke.beads.beads_hierarchy import NEEDS_DECOMPOSITION_LABEL


class TestDeferItem:
    """Tests for defer_item."""

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_successful_defer(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import defer_item

        mock_run_bd.return_value = Mock()

        result = defer_item("item-1", "Too complex for single agent")

        assert result is True
        calls = mock_run_bd.call_args_list
        # First call: update --status backlog --add-label needs-decomposition
        update_call = calls[0]
        update_args = update_call[0][0]
        assert "update" in update_args
        assert "--status" in update_args
        assert "backlog" in update_args
        assert "--add-label" in update_args
        assert NEEDS_DECOMPOSITION_LABEL in update_args

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_returns_false_on_update_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import defer_item

        mock_run_bd.side_effect = subprocess.CalledProcessError(
            1, "bd", stderr="error"
        )

        result = defer_item("item-1", "reason")

        assert result is False

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_adds_comment_with_reason(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import defer_item

        mock_run_bd.return_value = Mock()

        defer_item("item-1", "Exceeded gate rejection cap (3/3)")

        calls = mock_run_bd.call_args_list
        comment_calls = [c for c in calls if "comments" in str(c)]
        assert len(comment_calls) >= 1, f"Expected comment call, got: {calls}"
        # Verify the comment includes auto-deferred prefix
        comment_text = str(comment_calls[0])
        assert "Auto-deferred" in comment_text

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_truncates_long_reason(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import defer_item

        mock_run_bd.return_value = Mock()
        long_reason = "x" * 600

        defer_item("item-1", long_reason)

        calls = mock_run_bd.call_args_list
        comment_calls = [c for c in calls if "comments" in str(c)]
        assert len(comment_calls) >= 1
        # The comment text should contain the truncated reason (max 500 chars)
        comment_arg = comment_calls[0][0][0][-1]  # last positional arg
        assert len(comment_arg) < 600

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_handles_timeout_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import defer_item

        mock_run_bd.side_effect = subprocess.TimeoutExpired("bd", 30)

        result = defer_item("item-1", "reason")

        assert result is False

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_handles_os_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import defer_item

        mock_run_bd.side_effect = OSError("no bd binary")

        result = defer_item("item-1", "reason")

        assert result is False


class TestNeedsDecompositionLabel:
    """Verify the label constant is properly defined and exported."""

    def test_label_value(self) -> None:
        assert NEEDS_DECOMPOSITION_LABEL == "needs-decomposition"

    def test_label_exported_from_beads(self) -> None:
        from pokepoke.beads.beads import NEEDS_DECOMPOSITION_LABEL as EXPORTED_LABEL

        assert EXPORTED_LABEL == "needs-decomposition"
