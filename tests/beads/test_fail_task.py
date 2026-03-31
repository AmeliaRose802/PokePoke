"""Tests for fail_task and record_item_failed functionality."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from pokepoke.beads.beads_item_stats_store import (
    get_summary,
    load_beads_item_stats,
    record_item_completed,
    record_item_created,
    record_item_failed,
)
from pokepoke.beads.beads_management import fail_task
from pokepoke.types import WorkItemResult

# ── record_item_failed tests ────────────────────────────────────────


class TestRecordItemFailed:
    """Tests for the 'failed' event type in beads_item_stats_store."""

    def test_record_failed_increments_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stats.json"
            s = record_item_failed("PP-1", agent_type="work", path=path)
            assert s["total_failed"] == 1
            assert s["total_created"] == 0
            assert s["total_completed"] == 0

    def test_failed_events_not_deduplicated(self) -> None:
        """Each failure attempt is counted separately (unlike created/completed)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stats.json"
            record_item_failed("PP-1", agent_type="work", path=path)
            s = record_item_failed("PP-1", agent_type="work", path=path)
            assert s["total_failed"] == 2

    def test_failed_tracked_per_agent_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stats.json"
            record_item_failed("PP-1", agent_type="work", path=path)
            s = record_item_failed("PP-2", agent_type="gate", path=path)
            assert s["by_agent_type"]["work"]["failed"] == 1
            assert s["by_agent_type"]["gate"]["failed"] == 1

    def test_mixed_events_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stats.json"
            record_item_created("PP-1", agent_type="work", path=path)
            record_item_completed("PP-2", agent_type="work", path=path)
            s = record_item_failed("PP-3", agent_type="work", path=path)
            assert s["total_created"] == 1
            assert s["total_completed"] == 1
            assert s["total_failed"] == 1
            assert s["by_agent_type"]["work"]["created"] == 1
            assert s["by_agent_type"]["work"]["completed"] == 1
            assert s["by_agent_type"]["work"]["failed"] == 1

    def test_empty_store_has_total_failed_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stats.json"
            summary = get_summary(path)
            assert summary["total_failed"] == 0

    def test_failed_event_persisted_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stats.json"
            record_item_failed("PP-1", agent_type="work", path=path)
            data = load_beads_item_stats(path)
            assert data["log"][0]["event"] == "failed"
            assert data["log"][0]["item_id"] == "PP-1"


# ── fail_task tests ─────────────────────────────────────────────────


class TestFailTask:
    """Tests for the fail_task consolidated failure function."""

    def test_adds_comment_to_beads_item(self) -> None:
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True) as mock_comment, \
             patch("pokepoke.beads.beads_item_stats_store.record_event"):
            result = fail_task("PP-1", "Test failure reason")
            assert result is True
            mock_comment.assert_called_once()
            call_args = mock_comment.call_args
            assert call_args[0][0] == "PP-1"
            assert "Test failure reason" in call_args[0][1]

    def test_records_failure_in_stats(self) -> None:
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True), \
             patch("pokepoke.beads.beads_item_stats_store.record_event") as mock_record:
            fail_task("PP-1", "Copilot session crashed", agent_type="work")
            mock_record.assert_called_once_with("failed", "PP-1", "work", path=None, repo_name="")

    def test_truncates_long_reasons(self) -> None:
        long_reason = "x" * 1000
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True) as mock_comment, \
             patch("pokepoke.beads.beads_item_stats_store.record_event"):
            fail_task("PP-1", long_reason)
            comment_text = mock_comment.call_args[0][1]
            assert len(comment_text) <= 520  # "❌ Agent failure: " prefix + 500 chars

    def test_returns_false_when_comment_fails(self) -> None:
        with patch("pokepoke.beads.beads_management.add_comment", return_value=False), \
             patch("pokepoke.beads.beads_item_stats_store.record_event"):
            result = fail_task("PP-1", "some error")
            assert result is False

    def test_survives_stats_recording_error(self) -> None:
        """fail_task should not raise even if stats recording fails."""
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True), \
             patch("pokepoke.beads.beads_item_stats_store.record_event", side_effect=OSError("disk full")):
            result = fail_task("PP-1", "some error")
            assert result is True

    def test_handles_empty_reason(self) -> None:
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True) as mock_comment, \
             patch("pokepoke.beads.beads_item_stats_store.record_event"):
            fail_task("PP-1", "")
            comment_text = mock_comment.call_args[0][1]
            assert "Unknown failure" in comment_text

    def test_custom_agent_type_passed_to_stats(self) -> None:
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True), \
             patch("pokepoke.beads.beads_item_stats_store.record_event") as mock_record:
            fail_task("PP-1", "gate rejected", agent_type="gate")
            mock_record.assert_called_once_with("failed", "PP-1", "gate", path=None, repo_name="")

    def test_default_agent_type_is_work(self) -> None:
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True), \
             patch("pokepoke.beads.beads_item_stats_store.record_event") as mock_record:
            fail_task("PP-1", "some error")
            mock_record.assert_called_once_with("failed", "PP-1", "work", path=None, repo_name="")

    def test_handles_none_reason(self) -> None:
        """None reason (even though type says str) should be handled gracefully."""
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True) as mock_comment, \
             patch("pokepoke.beads.beads_item_stats_store.record_event"):
            fail_task("PP-1", None)  # type: ignore[arg-type]
            comment_text = mock_comment.call_args[0][1]
            assert "Unknown failure" in comment_text


# ── WorkItemResult.failure_reason tests ─────────────────────────────


class TestWorkItemResultFailureReason:
    """Tests for the failure_reason field on WorkItemResult."""

    def test_success_result_has_no_reason(self) -> None:
        result = WorkItemResult(success=True, request_count=1)
        assert result.failure_reason is None

    def test_failure_result_carries_reason(self) -> None:
        result = WorkItemResult(
            success=False, request_count=0, failure_reason="Copilot crashed"
        )
        assert result.failure_reason == "Copilot crashed"

    def test_failure_reason_defaults_to_none(self) -> None:
        result = WorkItemResult(success=False, request_count=0)
        assert result.failure_reason is None


# ── FakeBeadsClient.fail_task tests ────────────────────────────────


class TestFakeBeadsClientFailTask:
    """Tests for the fail_task method on FakeBeadsClient."""

    def test_records_call_and_comment(self) -> None:
        from tests.fakes import FakeBeadsClient
        client = FakeBeadsClient()
        assert client.fail_task("PP-1", "crashed") is True
        assert client.call_count("fail_task") == 1
        comments = client.get_comments("PP-1")
        assert any("crashed" in c for c in comments)

    def test_tracks_failure_reason(self) -> None:
        from tests.fakes import FakeBeadsClient
        client = FakeBeadsClient()
        client.fail_task("PP-1", "timeout exceeded")
        assert client._failure_reasons["PP-1"] == "timeout exceeded"

    def test_respects_fail_methods(self) -> None:
        from tests.fakes import FakeBeadsClient
        client = FakeBeadsClient()
        client.fail_methods.add("fail_task")
        assert client.fail_task("PP-1", "error") is False
