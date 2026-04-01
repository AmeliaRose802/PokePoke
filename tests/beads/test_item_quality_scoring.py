"""Tests for per-item quality scoring in beads_item_stats_store."""

import json
import tempfile
from pathlib import Path

from pokepoke.beads.beads_item_stats_store import (
    get_item_stats,
    get_items_needing_attention,
    load_beads_item_stats,
    record_item_attempt,
    record_item_completed,
    record_item_created,
)


def test_record_attempt_creates_item_metrics() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        metrics = record_item_attempt(
            "PP-001", success=True, tokens_used=500, duration_seconds=30.0, path=path,
        )
        assert metrics["attempt_count"] == 1
        assert metrics["total_tokens"] == 500
        assert metrics["total_duration_seconds"] == 30.0
        assert metrics["last_result"] == "success"
        assert metrics["consecutive_failures"] == 0
        assert metrics["needs_human_attention"] is False
        assert metrics["first_attempted"] != ""
        assert metrics["last_attempted"] != ""


def test_record_attempt_accumulates_across_runs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        record_item_attempt("PP-001", success=True, tokens_used=100, duration_seconds=10.0, path=path)
        metrics = record_item_attempt(
            "PP-001", success=True, tokens_used=200, duration_seconds=20.0, path=path,
        )
        assert metrics["attempt_count"] == 2
        assert metrics["total_tokens"] == 300
        assert metrics["total_duration_seconds"] == 30.0


def test_consecutive_failures_trigger_needs_human_attention() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        for i in range(2):
            metrics = record_item_attempt(
                "PP-002", success=False, failure_reason=f"fail {i+1}",
                attention_threshold=3, path=path,
            )
        assert metrics["consecutive_failures"] == 2
        assert metrics["needs_human_attention"] is False

        metrics = record_item_attempt(
            "PP-002", success=False, failure_reason="fail 3",
            attention_threshold=3, path=path,
        )
        assert metrics["consecutive_failures"] == 3
        assert metrics["needs_human_attention"] is True
        assert len(metrics["failure_reasons"]) == 3


def test_success_resets_consecutive_failures_and_flag() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        for _ in range(4):
            record_item_attempt(
                "PP-003", success=False, failure_reason="oops",
                attention_threshold=3, path=path,
            )
        metrics = record_item_attempt(
            "PP-003", success=True, tokens_used=50, duration_seconds=5.0, path=path,
        )
        assert metrics["consecutive_failures"] == 0
        assert metrics["needs_human_attention"] is False
        assert metrics["last_result"] == "success"
        assert metrics["attempt_count"] == 5


def test_get_item_stats_returns_empty_for_unknown() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        metrics = get_item_stats("NONEXISTENT", path=path)
        assert metrics["attempt_count"] == 0
        assert metrics["needs_human_attention"] is False


def test_get_item_stats_returns_persisted_data() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        record_item_attempt("PP-004", success=True, tokens_used=999, duration_seconds=42.0, path=path)
        metrics = get_item_stats("PP-004", path=path)
        assert metrics["attempt_count"] == 1
        assert metrics["total_tokens"] == 999
        assert metrics["total_duration_seconds"] == 42.0


def test_get_items_needing_attention() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        # Create one item that needs attention, one that doesn't
        for _ in range(3):
            record_item_attempt(
                "PP-BAD", success=False, failure_reason="broken",
                attention_threshold=3, path=path,
            )
        record_item_attempt("PP-GOOD", success=True, path=path)

        needing = get_items_needing_attention(path=path)
        assert "PP-BAD" in needing
        assert "PP-GOOD" not in needing
        assert needing["PP-BAD"]["consecutive_failures"] == 3


def test_get_items_needing_attention_empty_store() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        assert get_items_needing_attention(path=path) == {}


def test_failure_reasons_capped() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        for i in range(15):
            record_item_attempt(
                "PP-MANY", success=False, failure_reason=f"reason-{i}",
                attention_threshold=100, path=path,
            )
        metrics = get_item_stats("PP-MANY", path=path)
        assert len(metrics["failure_reasons"]) == 10
        assert metrics["failure_reasons"][0] == "reason-5"
        assert metrics["failure_reasons"][-1] == "reason-14"


def test_item_metrics_coexist_with_log_and_summary() -> None:
    """Per-item metrics should not interfere with existing log/summary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        record_item_created("PP-010", agent_type="janitor", path=path)
        record_item_completed("PP-010", agent_type="work", path=path)
        record_item_attempt("PP-010", success=True, tokens_used=100, path=path)

        data = load_beads_item_stats(path)
        assert data["summary"]["total_created"] == 1
        assert data["summary"]["total_completed"] == 1
        assert data["items"]["PP-010"]["attempt_count"] == 1


def test_normalize_migrates_store_without_items_key() -> None:
    """Old stores without 'items' key should get it added on load."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        old_data = {"log": [], "summary": {"total_created": 0, "total_completed": 0,
                                            "total_failed": 0, "net_delta": 0,
                                            "by_agent_type": {}, "last_updated": ""}}
        path.write_text(json.dumps(old_data), encoding="utf-8")

        data = load_beads_item_stats(path)
        assert "items" in data
        assert isinstance(data["items"], dict)
        assert data["items"] == {}


def test_record_attempt_negative_tokens_clamped() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        metrics = record_item_attempt("PP-NEG", success=True, tokens_used=-100, path=path)
        assert metrics["total_tokens"] == 0


def test_record_attempt_negative_duration_clamped() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        metrics = record_item_attempt("PP-NEG", success=True, duration_seconds=-5.0, path=path)
        assert metrics["total_duration_seconds"] == 0.0


def test_multiple_items_tracked_independently() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        record_item_attempt("PP-A", success=True, tokens_used=100, path=path)
        record_item_attempt("PP-B", success=False, failure_reason="err", attention_threshold=1, path=path)

        a = get_item_stats("PP-A", path=path)
        b = get_item_stats("PP-B", path=path)
        assert a["last_result"] == "success"
        assert b["last_result"] == "failed"
        assert b["needs_human_attention"] is True
        assert a["needs_human_attention"] is False


def test_record_attempt_no_failure_reason_on_failure() -> None:
    """Failing without a reason should still increment consecutive_failures."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        metrics = record_item_attempt("PP-NR", success=False, attention_threshold=1, path=path)
        assert metrics["consecutive_failures"] == 1
        assert metrics["needs_human_attention"] is True
        assert metrics["failure_reasons"] == []


def test_persists_item_metrics_to_disk() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        record_item_attempt("PP-DISK", success=True, tokens_used=42, path=path)

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "items" in raw
        assert raw["items"]["PP-DISK"]["total_tokens"] == 42
