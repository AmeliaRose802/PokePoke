"""Tests for beads_recovery — atomic manifest writes and core recovery logic.

This file ensures the pre-commit coverage hook can discover tests for
beads_recovery.py via the standard naming convention (test_<module>.py).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.beads.beads_manifest_utils import (
    _load_failed_unassign_manifest,
    add_failed_unassign,
    remove_failed_unassign,
    unassign_with_retry,
)
from pokepoke.beads.beads_recovery import (
    get_failed_unassign_count,
    retry_failed_unassigns,
)


class TestAddRemoveFailedUnassign:
    """Test add/remove with manifest_lock mocked."""

    def test_add_persists_item(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            add_failed_unassign("item-42", "connection refused")
            loaded = _load_failed_unassign_manifest()
            assert "item-42" in loaded
            assert loaded["item-42"].reason == "connection refused"

    def test_remove_deletes_item(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps({"item-1": {"reason": "x", "timestamp": "t"}}),
            encoding="utf-8",
        )
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            remove_failed_unassign("item-1")
            assert _load_failed_unassign_manifest() == {}

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps({}), encoding="utf-8")
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            remove_failed_unassign("ghost")
            assert _load_failed_unassign_manifest() == {}


class TestGetFailedUnassignCount:
    def test_count_empty(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=tmp_path / "nope.json",
        ):
            assert get_failed_unassign_count() == 0

    def test_count_with_items(self, tmp_path: Path) -> None:
        import json
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"a": {"reason": "r", "timestamp": "t"}, "b": {"reason": "r", "timestamp": "t"}}), encoding="utf-8")
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=p,
        ):
            assert get_failed_unassign_count() == 2


class TestUnassignWithRetry:
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    def test_success_on_first_attempt(self, mock_sleep: MagicMock) -> None:
        with patch("pokepoke.beads.beads_management.unassign_item", return_value=True):
            assert unassign_with_retry("item-1") is True
        mock_sleep.assert_not_called()

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    def test_success_on_retry(self, mock_sleep: MagicMock) -> None:
        with patch("pokepoke.beads.beads_management.unassign_item", side_effect=[False, False, True]):
            assert unassign_with_retry("item-1") is True

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep: MagicMock, mock_add: MagicMock) -> None:
        with patch("pokepoke.beads.beads_management.unassign_item", return_value=False):
            assert unassign_with_retry("item-1") is False
        mock_add.assert_called_once()

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    def test_exception_triggers_retry(self, mock_sleep: MagicMock, mock_add: MagicMock) -> None:
        with patch("pokepoke.beads.beads_management.unassign_item", side_effect=RuntimeError("boom")):
            assert unassign_with_retry("item-1") is False
        mock_add.assert_called_once()

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep: MagicMock) -> None:
        with patch("pokepoke.beads.beads_management.unassign_item", side_effect=[False, False, True]):
            unassign_with_retry("item-1")
        assert mock_sleep.call_count == 2
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays[0] < delays[1]


class TestRetryFailedUnassigns:
    def test_empty_manifest_returns_zero(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=tmp_path / "nope.json",
        ):
            assert retry_failed_unassigns() == 0

    def test_recovers_items(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps({"item-1": {"reason": "fail", "timestamp": "t"}}),
            encoding="utf-8",
        )
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_management.unassign_item", return_value=True),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            assert retry_failed_unassigns() == 1

    def test_still_failing_items_remain(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps({"item-1": {"reason": "fail", "timestamp": "t"}}),
            encoding="utf-8",
        )
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_recovery._unassign", side_effect=RuntimeError("nope")),
        ):
            assert retry_failed_unassigns() == 0
