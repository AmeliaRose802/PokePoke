"""Tests for beads_recovery — atomic manifest writes and core recovery logic.

This file ensures the pre-commit coverage hook can discover tests for
beads_recovery.py via the standard naming convention (test_<module>.py).
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

from pokepoke.beads_recovery import (
    _load_failed_unassign_manifest,
    _save_failed_unassign_manifest,
    _add_failed_unassign,
    _remove_failed_unassign,
    get_failed_unassign_count,
    unassign_with_retry,
    retry_failed_unassigns,
)


class TestManifestAtomicWrite:
    """Verify that manifest saves use the atomic tmp+rename pattern."""

    def test_save_writes_via_tmp_then_rename(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".pokepoke" / "failed_unassigns.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            data = {"item-1": {"reason": "timeout", "timestamp": "2026-01-01T00:00:00"}}
            _save_failed_unassign_manifest(data)

            assert manifest_path.exists()
            # The tmp file should have been renamed away
            assert not manifest_path.with_suffix(".tmp").exists()

            import json
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert loaded == data

    def test_save_creates_parent_directory(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "new_dir" / "manifest.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _save_failed_unassign_manifest({"x": {"reason": "test", "timestamp": "t"}})
            assert manifest_path.exists()

    def test_save_logs_warning_on_os_error(self, tmp_path: Path) -> None:
        # Use a path whose parent cannot be created (file in place of dir)
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file", encoding="utf-8")
        manifest_path = blocker / "sub" / "manifest.json"
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            # Should not raise, just log a warning
            _save_failed_unassign_manifest({"a": {"reason": "r", "timestamp": "t"}})


class TestManifestLoadEdgeCases:
    """Test loading edge cases."""

    def test_load_returns_empty_for_missing(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=tmp_path / "nope.json",
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_load_returns_empty_for_corrupt(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{truncated", encoding="utf-8")
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=bad,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_load_returns_empty_for_non_dict(self, tmp_path: Path) -> None:
        arr = tmp_path / "arr.json"
        arr.write_text("[1]", encoding="utf-8")
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=arr,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_load_valid_manifest(self, tmp_path: Path) -> None:
        import json
        p = tmp_path / "ok.json"
        data = {"item-1": {"reason": "fail", "timestamp": "t"}}
        p.write_text(json.dumps(data), encoding="utf-8")
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=p,
        ):
            assert _load_failed_unassign_manifest() == data


class TestAddRemoveFailedUnassign:
    """Test add/remove with manifest_lock mocked."""

    def test_add_persists_item(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        with (
            patch(
                "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads_recovery.manifest_lock", return_value=MagicMock()),
        ):
            _add_failed_unassign("item-42", "connection refused")
            loaded = _load_failed_unassign_manifest()
            assert "item-42" in loaded
            assert loaded["item-42"]["reason"] == "connection refused"

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
                "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads_recovery.manifest_lock", return_value=MagicMock()),
        ):
            _remove_failed_unassign("item-1")
            assert _load_failed_unassign_manifest() == {}

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps({}), encoding="utf-8")
        with (
            patch(
                "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads_recovery.manifest_lock", return_value=MagicMock()),
        ):
            _remove_failed_unassign("ghost")
            assert _load_failed_unassign_manifest() == {}


class TestGetFailedUnassignCount:
    def test_count_empty(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=tmp_path / "nope.json",
        ):
            assert get_failed_unassign_count() == 0

    def test_count_with_items(self, tmp_path: Path) -> None:
        import json
        p = tmp_path / "m.json"
        p.write_text(json.dumps({"a": {"reason": "r", "timestamp": "t"}, "b": {"reason": "r", "timestamp": "t"}}), encoding="utf-8")
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
            return_value=p,
        ):
            assert get_failed_unassign_count() == 2


class TestUnassignWithRetry:
    @patch("pokepoke.beads_recovery.time.sleep")
    def test_success_on_first_attempt(self, mock_sleep: MagicMock) -> None:
        with patch("pokepoke.beads_recovery._unassign", return_value=True):
            assert unassign_with_retry("item-1") is True
        mock_sleep.assert_not_called()

    @patch("pokepoke.beads_recovery.time.sleep")
    def test_success_on_retry(self, mock_sleep: MagicMock) -> None:
        with patch("pokepoke.beads_recovery._unassign", side_effect=[False, False, True]):
            assert unassign_with_retry("item-1") is True

    @patch("pokepoke.beads_recovery._add_failed_unassign")
    @patch("pokepoke.beads_recovery.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep: MagicMock, mock_add: MagicMock) -> None:
        with patch("pokepoke.beads_recovery._unassign", return_value=False):
            assert unassign_with_retry("item-1") is False
        mock_add.assert_called_once()

    @patch("pokepoke.beads_recovery._add_failed_unassign")
    @patch("pokepoke.beads_recovery.time.sleep")
    def test_exception_triggers_retry(self, mock_sleep: MagicMock, mock_add: MagicMock) -> None:
        with patch("pokepoke.beads_recovery._unassign", side_effect=RuntimeError("boom")):
            assert unassign_with_retry("item-1") is False
        mock_add.assert_called_once()

    @patch("pokepoke.beads_recovery.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep: MagicMock) -> None:
        with patch("pokepoke.beads_recovery._unassign", side_effect=[False, False, True]):
            unassign_with_retry("item-1")
        assert mock_sleep.call_count == 2
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays[0] < delays[1]


class TestRetryFailedUnassigns:
    def test_empty_manifest_returns_zero(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
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
                "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads_recovery._unassign", return_value=True),
            patch("pokepoke.beads_recovery.manifest_lock", return_value=MagicMock()),
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
                "pokepoke.beads_recovery._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads_recovery._unassign", side_effect=RuntimeError("nope")),
        ):
            assert retry_failed_unassigns() == 0
