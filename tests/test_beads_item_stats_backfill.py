"""Tests for beads_item_stats_backfill module."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from pokepoke.beads_item_stats_backfill import (
    _determine_agent_type,
    _get_all_beads_items,
    backfill_from_beads_db,
)


def test_determine_agent_type_human():
    """Test agent type detection for human creators."""
    assert _determine_agent_type("Amelia Payne") == "human"
    assert _determine_agent_type("ameliapayne@microsoft.com") == "human"
    assert _determine_agent_type("amelia") == "human"
    assert _determine_agent_type("AMELIA PAYNE") == "human"


def test_determine_agent_type_unknown():
    """Test agent type detection for unknown creators."""
    assert _determine_agent_type("") == "unknown"
    assert _determine_agent_type("bot@example.com") == "unknown"
    assert _determine_agent_type("system") == "unknown"


@patch("pokepoke.beads_item_stats_backfill.subprocess.run")
def test_get_all_beads_items_success(mock_run):
    """Test fetching beads items successfully."""
    mock_run.return_value = MagicMock(
        stdout=json.dumps([
            {"id": "PokePoke-123", "title": "Test Item"},
            {"id": "PokePoke-456", "title": "Another Item"},
        ])
    )

    items = _get_all_beads_items()

    assert len(items) == 2
    assert items[0]["id"] == "PokePoke-123"
    assert items[1]["id"] == "PokePoke-456"
    mock_run.assert_called_once_with(
        ["bd", "list", "--json"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=True,
        timeout=30,
    )


@patch("pokepoke.beads_item_stats_backfill.subprocess.run")
def test_get_all_beads_items_failure(mock_run):
    """Test handling of beads fetch failure."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "bd list")

    items = _get_all_beads_items()

    assert items == []


@patch("pokepoke.beads_item_stats_backfill.subprocess.run")
def test_get_all_beads_items_timeout(mock_run):
    """Test handling of beads fetch timeout."""
    mock_run.side_effect = subprocess.TimeoutExpired("bd list", 30)

    items = _get_all_beads_items()

    assert items == []


def test_backfill_nothing_needed(tmp_path):
    """Test backfill when all items already have created events."""
    stats_file = tmp_path / "beads_item_stats.json"
    stats_file.write_text(
        json.dumps({
            "log": [
                {
                    "event": "created",
                    "item_id": "PokePoke-123",
                    "agent_type": "work",
                    "timestamp": "2024-01-01T00:00:00Z",
                },
                {
                    "event": "completed",
                    "item_id": "PokePoke-123",
                    "agent_type": "work",
                    "timestamp": "2024-01-01T01:00:00Z",
                },
            ],
            "summary": {
                "total_created": 1,
                "total_completed": 1,
                "net_delta": 0,
                "by_agent_type": {},
            },
        })
    )

    with patch("pokepoke.beads_item_stats_backfill._get_all_beads_items") as mock_get_items:
        mock_get_items.return_value = [
            {"id": "PokePoke-123", "title": "Test", "created_by": "Amelia Payne"}
        ]

        result = backfill_from_beads_db(stats_path=stats_file, silent=True)

    assert result["backfilled"] == 0
    assert result["already_complete"] is True
    assert result["total_created"] == 1
    assert result["total_completed"] == 1


def test_backfill_from_db(tmp_path):
    """Test backfilling items from current beads database."""
    stats_file = tmp_path / "beads_item_stats.json"
    stats_file.write_text(
        json.dumps({
            "log": [
                {
                    "event": "completed",
                    "item_id": "PokePoke-456",
                    "agent_type": "work",
                    "timestamp": "2024-01-01T01:00:00Z",
                },
            ],
            "summary": {
                "total_created": 0,
                "total_completed": 1,
                "net_delta": -1,
                "by_agent_type": {},
            },
        })
    )

    with patch("pokepoke.beads_item_stats_backfill._get_all_beads_items") as mock_get_items:
        mock_get_items.return_value = [
            {"id": "PokePoke-123", "title": "New Item", "created_by": "Amelia Payne", "created_at": "2024-01-01T00:00:00Z"},
            {"id": "PokePoke-456", "title": "Existing", "created_by": "bot", "created_at": "2024-01-01T00:30:00Z"},
        ]

        result = backfill_from_beads_db(stats_path=stats_file, silent=True)

    # Both items from DB get backfilled (PokePoke-123 is new, PokePoke-456 exists but has no created event yet)
    # Note: PokePoke-456 appears in both DB and completed history, but gets backfilled from DB first
    assert result["backfilled"] == 2
    assert result["already_complete"] is False
    assert result["total_created"] == 2
    assert result["total_completed"] == 1
    assert result["net_delta"] == 1

    # Verify the log was updated
    with stats_file.open() as f:
        stats = json.load(f)

    created_events = [e for e in stats["log"] if e["event"] == "created"]
    assert len(created_events) == 2

    # Check that PokePoke-123 was backfilled with human agent type
    item_123 = next(e for e in created_events if e["item_id"] == "PokePoke-123")
    assert item_123["agent_type"] == "human"
    assert item_123["timestamp"] == "2024-01-01T00:00:00Z"

    # Check that PokePoke-456 was backfilled from DB (not from completed history)
    item_456 = next(e for e in created_events if e["item_id"] == "PokePoke-456")
    assert item_456["agent_type"] == "unknown"  # From DB with "bot" creator
    assert item_456["timestamp"] == "2024-01-01T00:30:00Z"


def test_backfill_from_completed_history(tmp_path):
    """Test backfilling items that only exist in completed history."""
    stats_file = tmp_path / "beads_item_stats.json"
    stats_file.write_text(
        json.dumps({
            "log": [
                {
                    "event": "completed",
                    "item_id": "PokePoke-old",
                    "agent_type": "janitor",
                    "timestamp": "2024-01-01T01:00:00Z",
                },
            ],
            "summary": {
                "total_created": 0,
                "total_completed": 1,
                "net_delta": -1,
                "by_agent_type": {},
            },
        })
    )

    with patch("pokepoke.beads_item_stats_backfill._get_all_beads_items") as mock_get_items:
        mock_get_items.return_value = []  # Item no longer in beads database

        result = backfill_from_beads_db(stats_path=stats_file, silent=True)

    assert result["backfilled"] == 1
    assert result["total_created"] == 1
    assert result["total_completed"] == 1
    assert result["net_delta"] == 0

    # Verify the created event was added with correct agent type
    with stats_file.open() as f:
        stats = json.load(f)

    created_events = [e for e in stats["log"] if e["event"] == "created"]
    assert len(created_events) == 1
    assert created_events[0]["item_id"] == "PokePoke-old"
    assert created_events[0]["agent_type"] == "janitor"  # Inherited from completed event


def test_backfill_idempotent(tmp_path):
    """Test that backfill is idempotent - running twice doesn't create duplicates."""
    stats_file = tmp_path / "beads_item_stats.json"
    stats_file.write_text(
        json.dumps({
            "log": [],
            "summary": {
                "total_created": 0,
                "total_completed": 0,
                "net_delta": 0,
                "by_agent_type": {},
            },
        })
    )

    with patch("pokepoke.beads_item_stats_backfill._get_all_beads_items") as mock_get_items:
        mock_get_items.return_value = [
            {"id": "PokePoke-123", "title": "Test", "created_by": "Amelia", "created_at": "2024-01-01T00:00:00Z"},
        ]

        # First backfill
        result1 = backfill_from_beads_db(stats_path=stats_file, silent=True)
        assert result1["backfilled"] == 1
        assert result1["total_created"] == 1

        # Second backfill - should be idempotent
        result2 = backfill_from_beads_db(stats_path=stats_file, silent=True)
        assert result2["backfilled"] == 0
        assert result2["already_complete"] is True
        assert result2["total_created"] == 1  # Still 1, not 2

    # Verify only one created event exists
    with stats_file.open() as f:
        stats = json.load(f)

    created_events = [e for e in stats["log"] if e["event"] == "created"]
    assert len(created_events) == 1
