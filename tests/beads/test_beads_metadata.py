"""Tests for beads metadata management (attempt tracking, gate rejection counts)."""

import json
import subprocess
from unittest.mock import Mock, patch

from pokepoke.beads.beads_metadata import (
    get_gate_rejection_count,
    get_total_attempts,
    increment_gate_rejection_count,
    increment_total_attempts,
)

# ---------------------------------------------------------------------------
# get_total_attempts
# ---------------------------------------------------------------------------

class TestGetTotalAttempts:
    """Tests for get_total_attempts."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_total_attempts_from_metadata(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout='[{"metadata":{"total_attempts":3}}]')
        mock_parse.return_value = [{"metadata": {"total_attempts": 3}}]

        assert get_total_attempts("item-1") == 3
        mock_run.assert_called_once_with(["show", "item-1", "--json"], check=False)

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_zero_when_no_metadata(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout='[{"id":"item-1"}]')
        mock_parse.return_value = [{"id": "item-1"}]

        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_zero_when_metadata_is_none(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout='[{"metadata": null}]')
        mock_parse.return_value = [{"metadata": None}]

        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_zero_when_metadata_not_dict(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout='[{"metadata": "string"}]')
        mock_parse.return_value = [{"metadata": "string"}]

        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_zero_when_parse_returns_none(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout="")
        mock_parse.return_value = None

        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_handles_dict_result(self, mock_parse, mock_run):
        """When _parse_beads_json returns a dict instead of list."""
        mock_run.return_value = Mock(stdout='{"metadata":{"total_attempts":5}}')
        mock_parse.return_value = {"metadata": {"total_attempts": 5}}

        assert get_total_attempts("item-1") == 5

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_subprocess_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd")

        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_json_decode_error(self, mock_run):
        mock_run.side_effect = json.JSONDecodeError("err", "doc", 0)

        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_value_error(self, mock_run):
        mock_run.side_effect = ValueError("bad value")

        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_type_error(self, mock_run):
        mock_run.side_effect = TypeError("bad type")

        assert get_total_attempts("item-1") == 0


# ---------------------------------------------------------------------------
# increment_total_attempts
# ---------------------------------------------------------------------------

class TestIncrementTotalAttempts:
    """Tests for increment_total_attempts."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_increments_existing_attempts(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": {"total_attempts": 2}}]
        mock_run.return_value = Mock(stdout="")

        result = increment_total_attempts("item-1")

        assert result is True
        # Second call should be the update with incremented value
        update_call = mock_run.call_args_list[1]
        args = update_call[0][0]
        assert args[0] == "update"
        assert args[1] == "item-1"
        assert args[2] == "--metadata"
        metadata = json.loads(args[3])
        assert metadata["total_attempts"] == 3

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_increments_from_zero_when_no_attempts(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": {}}]
        mock_run.return_value = Mock(stdout="")

        result = increment_total_attempts("item-1")

        assert result is True
        update_call = mock_run.call_args_list[1]
        metadata = json.loads(update_call[0][0][3])
        assert metadata["total_attempts"] == 1

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_handles_no_metadata_key(self, mock_parse, mock_run):
        mock_parse.return_value = [{"id": "item-1"}]
        mock_run.return_value = Mock(stdout="")

        result = increment_total_attempts("item-1")

        assert result is True
        update_call = mock_run.call_args_list[1]
        metadata = json.loads(update_call[0][0][3])
        assert metadata["total_attempts"] == 1

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_preserves_other_metadata_fields(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": {"total_attempts": 1, "other_key": "value"}}]
        mock_run.return_value = Mock(stdout="")

        result = increment_total_attempts("item-1")

        assert result is True
        update_call = mock_run.call_args_list[1]
        metadata = json.loads(update_call[0][0][3])
        assert metadata["total_attempts"] == 2
        assert metadata["other_key"] == "value"

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_false_when_parse_returns_none(self, mock_parse, mock_run):
        mock_parse.return_value = None
        mock_run.return_value = Mock(stdout="")

        result = increment_total_attempts("item-1")

        assert result is False

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_false_on_subprocess_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd")

        assert increment_total_attempts("item-1") is False

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_handles_metadata_not_dict(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": "not-a-dict"}]
        mock_run.return_value = Mock(stdout="")

        result = increment_total_attempts("item-1")

        assert result is True
        update_call = mock_run.call_args_list[1]
        metadata = json.loads(update_call[0][0][3])
        assert metadata["total_attempts"] == 1


# ---------------------------------------------------------------------------
# get_gate_rejection_count
# ---------------------------------------------------------------------------

class TestGetGateRejectionCount:
    """Tests for get_gate_rejection_count."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_count_from_metadata(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout="")
        mock_parse.return_value = [{"metadata": {"gate_rejection_count": 5}}]

        assert get_gate_rejection_count("item-1") == 5

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_zero_when_no_metadata(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout="")
        mock_parse.return_value = [{"id": "item-1"}]

        assert get_gate_rejection_count("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_zero_when_parse_returns_none(self, mock_parse, mock_run):
        mock_run.return_value = Mock(stdout="")
        mock_parse.return_value = None

        assert get_gate_rejection_count("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd")

        assert get_gate_rejection_count("item-1") == 0


# ---------------------------------------------------------------------------
# increment_gate_rejection_count
# ---------------------------------------------------------------------------

class TestIncrementGateRejectionCount:
    """Tests for increment_gate_rejection_count."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_increments_existing_count(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": {"gate_rejection_count": 3}}]
        mock_run.return_value = Mock(stdout="")

        result = increment_gate_rejection_count("item-1")

        assert result == 4
        update_call = mock_run.call_args_list[1]
        metadata = json.loads(update_call[0][0][3])
        assert metadata["gate_rejection_count"] == 4

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_increments_from_zero(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": {}}]
        mock_run.return_value = Mock(stdout="")

        result = increment_gate_rejection_count("item-1")

        assert result == 1

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_returns_negative_one_when_parse_returns_none(self, mock_parse, mock_run):
        mock_parse.return_value = None
        mock_run.return_value = Mock(stdout="")

        result = increment_gate_rejection_count("item-1")

        assert result == -1

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_negative_one_on_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd")

        assert increment_gate_rejection_count("item-1") == -1

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_handles_metadata_not_dict(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": "not-a-dict"}]
        mock_run.return_value = Mock(stdout="")

        result = increment_gate_rejection_count("item-1")

        assert result == 1

    @patch("pokepoke.beads.beads_metadata._run_bd")
    @patch("pokepoke.beads.beads_metadata._parse_beads_json")
    def test_preserves_other_metadata_fields(self, mock_parse, mock_run):
        mock_parse.return_value = [{"metadata": {"gate_rejection_count": 1, "total_attempts": 5}}]
        mock_run.return_value = Mock(stdout="")

        result = increment_gate_rejection_count("item-1")

        assert result == 2
        update_call = mock_run.call_args_list[1]
        metadata = json.loads(update_call[0][0][3])
        assert metadata["gate_rejection_count"] == 2
        assert metadata["total_attempts"] == 5
