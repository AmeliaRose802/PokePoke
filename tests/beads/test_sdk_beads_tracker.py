"""Tests for pokepoke.beads.sdk_beads_tracker."""

import json
from unittest.mock import MagicMock, patch

from pokepoke.beads.sdk_beads_tracker import (
    extract_command,
    is_beads_create,
    parse_created_items,
    record_items_created,
)


class TestExtractCommand:
    """Unit tests for extract_command."""

    def test_dict_with_command_key(self):
        assert extract_command({"command": "bd create"}) == "bd create"

    def test_dict_without_command_key(self):
        result = extract_command({"other": "value"})
        assert "other" in result

    def test_dict_with_non_string_command(self):
        result = extract_command({"command": 123})
        assert "123" in result

    def test_string_input(self):
        assert extract_command("bd create task") == "bd create task"

    def test_none_input(self):
        assert extract_command(None) == "None"

    def test_list_input(self):
        result = extract_command(["bd", "create"])
        assert "bd" in result


class TestIsBeadsCreate:
    """Unit tests for is_beads_create."""

    def test_bd_create(self):
        assert is_beads_create("bd create task --title 'Test'")

    def test_br_create(self):
        assert is_beads_create("br create feature --title 'X'")

    def test_case_insensitive(self):
        assert is_beads_create("BD Create task")
        assert is_beads_create("Br CREATE task")

    def test_non_create_command(self):
        assert not is_beads_create("bd ready --json")
        assert not is_beads_create("bd show item-1")

    def test_empty_string(self):
        assert not is_beads_create("")

    def test_partial_match(self):
        assert not is_beads_create("abdcreate")

    def test_create_in_middle_of_command(self):
        assert is_beads_create("echo hello && bd create task")


class TestParseCreatedItems:
    """Unit tests for parse_created_items."""

    def test_empty_string(self):
        assert parse_created_items("") == []

    def test_none_input(self):
        assert parse_created_items(None) == []

    def test_json_dict_with_id_and_title(self):
        data = json.dumps({"id": "PokePoke-abc", "title": "My task"})
        result = parse_created_items(data)
        assert result == [("PokePoke-abc", "My task")]

    def test_json_dict_with_id_only(self):
        data = json.dumps({"id": "PokePoke-xyz"})
        result = parse_created_items(data)
        assert result == [("PokePoke-xyz", "")]

    def test_json_dict_without_id(self):
        data = json.dumps({"title": "No ID"})
        result = parse_created_items(data)
        assert result == []

    def test_json_list(self):
        data = json.dumps([
            {"id": "PokePoke-a1", "title": "First"},
            {"id": "PokePoke-b2", "title": "Second"},
        ])
        result = parse_created_items(data)
        assert result == [("PokePoke-a1", "First"), ("PokePoke-b2", "Second")]

    def test_json_list_with_non_dict_entries(self):
        data = json.dumps([
            {"id": "PokePoke-ok", "title": "Good"},
            "not a dict",
            42,
        ])
        result = parse_created_items(data)
        assert result == [("PokePoke-ok", "Good")]

    def test_json_dict_non_string_title(self):
        data = json.dumps({"id": "PokePoke-t", "title": 123})
        result = parse_created_items(data)
        assert result == [("PokePoke-t", "")]

    def test_fallback_regex(self):
        text = "Created item PokePoke-12ab successfully"
        result = parse_created_items(text)
        assert result == [("PokePoke-12ab", "")]

    def test_fallback_regex_multiple(self):
        text = "Items PokePoke-aaa and PokePoke-bbb created"
        result = parse_created_items(text)
        assert len(result) == 2
        ids = {item[0] for item in result}
        assert "PokePoke-aaa" in ids
        assert "PokePoke-bbb" in ids

    def test_invalid_json_falls_back_to_regex(self):
        text = "not json PokePoke-fallback here"
        result = parse_created_items(text)
        assert result == [("PokePoke-fallback", "")]


class TestRecordItemsCreated:
    """Unit tests for record_items_created."""

    def test_empty_items_does_nothing(self):
        # Should not raise or import anything
        record_items_created([])

    @patch("pokepoke.stats.session_stats_registry.get_current_session_stats")
    @patch("pokepoke.stats.metrics_context.get_current_agent_type")
    @patch("pokepoke.beads.beads_item_stats_store.record_item_created")
    def test_records_items(self, mock_record, mock_agent_type, mock_stats):
        mock_agent_type.return_value = "work"
        mock_session_stats = MagicMock()
        mock_stats.return_value = mock_session_stats
        mock_record.return_value = {"total_created": 5, "total_completed": 3}

        record_items_created([("id-1", "Title 1"), ("id-2", "Title 2")])

        assert mock_record.call_count == 2
        mock_session_stats.record_created_item.assert_called()
        mock_session_stats.set_lifetime_beads_item_totals.assert_called_once_with(
            created=5, completed=3,
        )

    @patch("pokepoke.stats.session_stats_registry.get_current_session_stats")
    @patch("pokepoke.stats.metrics_context.get_current_agent_type")
    @patch("pokepoke.beads.beads_item_stats_store.record_item_created")
    def test_handles_none_stats(self, mock_record, mock_agent_type, mock_stats):
        mock_agent_type.return_value = "work"
        mock_stats.return_value = None
        mock_record.return_value = {"total_created": 1, "total_completed": 0}

        # Should not raise even with stats=None
        record_items_created([("id-1", "Title")])
        mock_record.assert_called_once()
