"""Tests for beads_recovery retry and failed-unassign recovery."""

from pathlib import Path
from unittest.mock import patch, Mock

from pokepoke.beads_recovery import (
    _load_failed_unassign_manifest,
    _save_failed_unassign_manifest,
    _add_failed_unassign,
    _remove_failed_unassign,
    get_failed_unassign_count,
    unassign_with_retry,
    retry_failed_unassigns,
)


class TestFailedUnassignManifest:
    """Tests for manifest load/save operations."""

    def test_load_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "missing.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_load_returns_empty_for_corrupt_json(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "corrupt.json"
        manifest_path.write_text("not json{{{", encoding="utf-8")
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_load_returns_empty_for_non_dict(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "list.json"
        manifest_path.write_text("[1,2,3]", encoding="utf-8")
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".pokepoke" / "failed_unassigns.json"
        manifest_path.parent.mkdir(parents=True)
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            data = {"item-1": {"reason": "bd failed", "timestamp": "2026-01-01T00:00:00"}}
            _save_failed_unassign_manifest(data)
            loaded = _load_failed_unassign_manifest()
            assert loaded == data


class TestAddRemoveFailedUnassign:
    """Tests for adding/removing items from the failed-unassign manifest."""

    def test_add_creates_entry(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _add_failed_unassign("item-abc", "network error")
            manifest = _load_failed_unassign_manifest()
            assert "item-abc" in manifest
            assert manifest["item-abc"]["reason"] == "network error"

    def test_remove_deletes_entry(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _add_failed_unassign("item-abc", "error")
            _remove_failed_unassign("item-abc")
            manifest = _load_failed_unassign_manifest()
            assert "item-abc" not in manifest

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _remove_failed_unassign("nonexistent")  # Should not raise


class TestGetFailedUnassignCount:
    """Tests for get_failed_unassign_count."""

    def test_returns_zero_when_empty(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=tmp_path / "missing.json",
        ):
            assert get_failed_unassign_count() == 0

    def test_returns_correct_count(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _add_failed_unassign("a", "err")
            _add_failed_unassign("b", "err")
            assert get_failed_unassign_count() == 2


class TestUnassignWithRetry:
    """Tests for unassign_with_retry."""

    @patch("pokepoke.beads_recovery.time.sleep")
    @patch("pokepoke.beads_management.unassign_item")
    def test_succeeds_on_first_try(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        mock_unassign.return_value = True
        assert unassign_with_retry("item-1") is True
        mock_unassign.assert_called_once_with("item-1")
        mock_sleep.assert_not_called()

    @patch("pokepoke.beads_recovery.time.sleep")
    @patch("pokepoke.beads_management.unassign_item")
    def test_succeeds_on_second_try(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        mock_unassign.side_effect = [False, True]
        assert unassign_with_retry("item-1") is True
        assert mock_unassign.call_count == 2
        mock_sleep.assert_called_once()

    @patch("pokepoke.beads_recovery._add_failed_unassign")
    @patch("pokepoke.beads_recovery.time.sleep")
    @patch("pokepoke.beads_management.unassign_item")
    def test_tracks_failure_after_all_retries(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        mock_unassign.return_value = False
        assert unassign_with_retry("item-stuck") is False
        assert mock_unassign.call_count == 3
        mock_add.assert_called_once()
        assert mock_add.call_args[0][0] == "item-stuck"

    @patch("pokepoke.beads_recovery._add_failed_unassign")
    @patch("pokepoke.beads_recovery.time.sleep")
    @patch("pokepoke.beads_management.unassign_item")
    def test_handles_exceptions(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        mock_unassign.side_effect = RuntimeError("bd crashed")
        assert unassign_with_retry("item-err") is False
        assert mock_unassign.call_count == 3
        mock_add.assert_called_once()

    @patch("pokepoke.beads_recovery.time.sleep")
    @patch("pokepoke.beads_management.unassign_item")
    def test_exponential_backoff_delays(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        mock_unassign.side_effect = [False, False, True]
        unassign_with_retry("item-1")
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == 1.0  # base delay
        assert delays[1] == 2.0  # doubled


class TestRetryFailedUnassigns:
    """Tests for retry_failed_unassigns recovery."""

    @patch("pokepoke.beads_management.unassign_item")
    def test_recovers_stuck_items(self, mock_unassign: Mock, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _add_failed_unassign("stuck-1", "previous failure")
            mock_unassign.return_value = True
            recovered = retry_failed_unassigns()
            assert recovered == 1
            assert get_failed_unassign_count() == 0

    @patch("pokepoke.beads_management.unassign_item")
    def test_leaves_still_failing_items(self, mock_unassign: Mock, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _add_failed_unassign("stuck-1", "err")
            _add_failed_unassign("stuck-2", "err")
            mock_unassign.side_effect = [True, RuntimeError("still broken")]
            recovered = retry_failed_unassigns()
            assert recovered == 1
            assert get_failed_unassign_count() == 1

    def test_returns_zero_when_no_manifest(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=tmp_path / "missing.json",
        ):
            assert retry_failed_unassigns() == 0
