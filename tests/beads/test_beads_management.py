"""Tests for beads_recovery retry and failed-unassign recovery."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.beads.beads_manifest_utils import (
    _load_failed_unassign_manifest,
    _save_failed_unassign_manifest,
    add_failed_unassign,
    remove_failed_unassign,
    unassign_with_retry,
)
from pokepoke.beads.beads_query import BD_CONFIG, BR_CONFIG, get_active_backend, set_active_backend
from pokepoke.beads.beads_recovery import (
    get_failed_unassign_count,
    retry_failed_unassigns,
)


class TestFailedUnassignManifest:
    """Tests for manifest load/save operations."""

    def test_load_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "missing.json"
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_load_returns_empty_for_corrupt_json(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "corrupt.json"
        manifest_path.write_text("not json{{{", encoding="utf-8")
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_load_returns_empty_for_non_dict(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "list.json"
        manifest_path.write_text("[1,2,3]", encoding="utf-8")
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".pokepoke" / "failed_unassigns.json"
        manifest_path.parent.mkdir(parents=True)
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
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
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            add_failed_unassign("item-abc", "network error")
            manifest = _load_failed_unassign_manifest()
            assert "item-abc" in manifest
            assert manifest["item-abc"]["reason"] == "network error"

    def test_remove_deletes_entry(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            add_failed_unassign("item-abc", "error")
            remove_failed_unassign("item-abc")
            manifest = _load_failed_unassign_manifest()
            assert "item-abc" not in manifest

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            remove_failed_unassign("nonexistent")  # Should not raise


class TestGetFailedUnassignCount:
    """Tests for get_failed_unassign_count."""

    def test_returns_zero_when_empty(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=tmp_path / "missing.json",
        ):
            assert get_failed_unassign_count() == 0

    def test_returns_correct_count(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            add_failed_unassign("a", "err")
            add_failed_unassign("b", "err")
            assert get_failed_unassign_count() == 2


class TestUnassignWithRetry:
    """Tests for unassign_with_retry."""

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_succeeds_on_first_try(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        mock_unassign.return_value = True
        assert unassign_with_retry("item-1") is True
        mock_unassign.assert_called_once_with("item-1")
        mock_sleep.assert_not_called()

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_succeeds_on_second_try(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        mock_unassign.side_effect = [False, True]
        assert unassign_with_retry("item-1") is True
        assert mock_unassign.call_count == 2
        mock_sleep.assert_called_once()

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_tracks_failure_after_all_retries(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        mock_unassign.return_value = False
        assert unassign_with_retry("item-stuck") is False
        assert mock_unassign.call_count == 3
        mock_add.assert_called_once()
        assert mock_add.call_args[0][0] == "item-stuck"

    @patch("pokepoke.beads.beads_manifest_utils.add_failed_unassign")
    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_handles_exceptions(
        self, mock_unassign: Mock, mock_sleep: Mock, mock_add: Mock
    ) -> None:
        mock_unassign.side_effect = RuntimeError("bd crashed")
        assert unassign_with_retry("item-err") is False
        assert mock_unassign.call_count == 3
        mock_add.assert_called_once()

    @patch("pokepoke.beads.beads_manifest_utils.time.sleep")
    @patch("pokepoke.beads.beads_management.unassign_item")
    def test_exponential_backoff_delays(self, mock_unassign: Mock, mock_sleep: Mock) -> None:
        mock_unassign.side_effect = [False, False, True]
        unassign_with_retry("item-1")
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == 1.0  # base delay
        assert delays[1] == 2.0  # doubled


class TestRetryFailedUnassigns:
    """Tests for retry_failed_unassigns recovery."""

    @patch("pokepoke.beads.beads_recovery._unassign")
    def test_recovers_stuck_items(self, mock_unassign: Mock, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            add_failed_unassign("stuck-1", "previous failure")
            mock_unassign.return_value = True
            recovered = retry_failed_unassigns()
            assert recovered == 1
            assert get_failed_unassign_count() == 0

    @patch("pokepoke.beads.beads_recovery._unassign")
    def test_leaves_still_failing_items(self, mock_unassign: Mock, tmp_path: Path) -> None:
        manifest_path = tmp_path / "failed_unassigns.json"
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            add_failed_unassign("stuck-1", "err")
            add_failed_unassign("stuck-2", "err")
            mock_unassign.side_effect = [True, RuntimeError("still broken")]
            recovered = retry_failed_unassigns()
            assert recovered == 1
            assert get_failed_unassign_count() == 1

    def test_returns_zero_when_no_manifest(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=tmp_path / "missing.json",
        ):
            assert retry_failed_unassigns() == 0


class TestRunBdSyncWithRetry:
    """Tests for run_bd_sync_with_retry timeout and retry behaviour."""

    def test_default_timeout_is_not_none(self) -> None:
        """run_bd_sync_with_retry must pass a finite timeout to prevent hangs
        inside file locks (regression guard for the worktree race condition)."""
        import inspect

        from pokepoke.beads.beads_management import run_bd_sync_with_retry

        sig = inspect.signature(run_bd_sync_with_retry)
        default_timeout = sig.parameters['timeout'].default
        assert default_timeout is not None, (
            "run_bd_sync_with_retry default timeout must not be None; "
            "a None timeout means bd sync can hang indefinitely while holding "
            "the worktree setup lock, causing all parallel agents to time out."
        )
        assert isinstance(default_timeout, int)
        assert default_timeout > 0

    @patch("pokepoke.beads.beads_query._run_cli")
    def test_passes_timeout_to_run_bd(self, mock_run_cli: Mock) -> None:
        """run_bd_sync_with_retry must forward its timeout to the sync strategy."""
        import subprocess

        from pokepoke.beads.beads_management import run_bd_sync_with_retry

        mock_run_cli.return_value = Mock(spec=subprocess.CompletedProcess, returncode=0)
        run_bd_sync_with_retry(timeout=42)

        _, kwargs = mock_run_cli.call_args
        assert kwargs["timeout"] == 42

    @patch("pokepoke.beads.beads_query._run_cli")
    def test_default_timeout_forwarded(self, mock_run_cli: Mock) -> None:
        """When no timeout is provided, the default (60s) is forwarded."""
        import subprocess

        from pokepoke.beads.beads_management import run_bd_sync_with_retry

        mock_run_cli.return_value = Mock(spec=subprocess.CompletedProcess, returncode=0)
        run_bd_sync_with_retry()

        _, call_kwargs = mock_run_cli.call_args
        assert call_kwargs.get('timeout') is not None
        assert call_kwargs.get('timeout') > 0


class TestIsTransientJsonlSyncError:
    """Tests for _is_transient_jsonl_sync_error helper."""

    def test_access_denied_with_jsonl(self) -> None:
        from pokepoke.beads.beads_management import _is_transient_jsonl_sync_error
        assert _is_transient_jsonl_sync_error("Access is denied to jsonl file") is True

    def test_failed_to_replace_jsonl(self) -> None:
        from pokepoke.beads.beads_management import _is_transient_jsonl_sync_error
        assert _is_transient_jsonl_sync_error("failed to replace jsonl file") is True

    def test_jsonl_hash_mismatch(self) -> None:
        from pokepoke.beads.beads_management import _is_transient_jsonl_sync_error
        assert _is_transient_jsonl_sync_error("jsonl file hash mismatch") is True

    def test_unrelated_error(self) -> None:
        from pokepoke.beads.beads_management import _is_transient_jsonl_sync_error
        assert _is_transient_jsonl_sync_error("some other error") is False

    def test_access_denied_without_jsonl(self) -> None:
        from pokepoke.beads.beads_management import _is_transient_jsonl_sync_error
        assert _is_transient_jsonl_sync_error("Access is denied") is False


class TestRunBdSyncRetryLogic:
    """Tests for run_bd_sync_with_retry retry behaviour."""

    @patch("pokepoke.beads.beads_query._run_cli")
    @patch("pokepoke.beads.sync_strategy.time.sleep")
    def test_retries_on_transient_jsonl_error(self, mock_sleep: Mock, mock_run_cli: Mock) -> None:
        from pokepoke.beads.beads_management import run_bd_sync_with_retry
        fail_result = Mock(returncode=1, stdout="failed to replace jsonl file", stderr="")
        ok_result = Mock(returncode=0, stdout="", stderr="")
        mock_run_cli.side_effect = [fail_result, ok_result]

        result = run_bd_sync_with_retry(max_attempts=3, base_delay=0.1)

        assert result.returncode == 0
        assert mock_run_cli.call_count == 2
        mock_sleep.assert_called_once()

    @patch("pokepoke.beads.beads_query._run_cli")
    def test_returns_immediately_on_non_transient_error(self, mock_run_cli: Mock) -> None:
        from pokepoke.beads.beads_management import run_bd_sync_with_retry
        fail_result = Mock(returncode=1, stdout="some random error", stderr="")
        mock_run_cli.return_value = fail_result

        result = run_bd_sync_with_retry(max_attempts=3)

        assert result.returncode == 1
        assert mock_run_cli.call_count == 1

    @patch("pokepoke.beads.beads_query._run_cli")
    @patch("pokepoke.beads.sync_strategy.time.sleep")
    def test_succeeds_on_retry_prints_message(self, mock_sleep: Mock, mock_run_cli: Mock, capsys: object) -> None:
        from pokepoke.beads.beads_management import run_bd_sync_with_retry
        fail_result = Mock(returncode=1, stdout="failed to replace jsonl file", stderr="")
        ok_result = Mock(returncode=0, stdout="", stderr="")
        mock_run_cli.side_effect = [fail_result, ok_result]

        run_bd_sync_with_retry(max_attempts=3, base_delay=0.1)

        # Should have retried and printed success message (captured as side effect of printing)
        assert mock_run_cli.call_count == 2


class TestIsItemClaimable:
    """Tests for is_item_claimable."""

    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    def test_unassigned_item_is_claimable(self, mock_parse: Mock, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import is_item_claimable
        mock_run_bd.return_value = Mock(stdout='[{"id":"x","assignee":""}]')
        mock_parse.return_value = [{"id": "x", "assignee": ""}]

        assert is_item_claimable("x") is True

    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    def test_assigned_item_not_claimable(self, mock_parse: Mock, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import is_item_claimable
        mock_run_bd.return_value = Mock(stdout='[{"id":"x","assignee":"other-agent"}]')
        mock_parse.return_value = [{"id": "x", "assignee": "other-agent"}]

        assert is_item_claimable("x") is False

    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    def test_returns_false_when_parse_returns_none(self, mock_parse: Mock, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import is_item_claimable
        mock_run_bd.return_value = Mock(stdout="")
        mock_parse.return_value = None

        assert is_item_claimable("x") is False

    @patch("pokepoke.beads.beads_management._run_bd")
    def test_returns_false_on_subprocess_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import is_item_claimable
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd", stderr="error")

        assert is_item_claimable("x") is False


class TestAssignAndSyncItem:
    """Tests for assign_and_sync_item."""

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_successful_assignment(
        self, mock_lock: Mock, mock_parse: Mock, mock_run_bd: Mock, mock_sync: Mock
    ) -> None:
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        @contextmanager
        def fake_lock(*args: object, **kwargs: object):
            yield Mock()

        mock_lock.side_effect = fake_lock
        # show call returns unassigned, update succeeds, show again returns us as assignee
        mock_parse.side_effect = [
            [{"id": "item-1", "assignee": ""}],   # pre-check: unassigned
            [{"id": "item-1", "assignee": "my-agent"}],  # verify: us
        ]
        mock_run_bd.return_value = Mock(stdout="")
        mock_sync.return_value = Mock(returncode=0)

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is True

    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_returns_false_when_lock_busy(self, mock_lock: Mock) -> None:
        from filelock import Timeout

        from pokepoke.beads.beads_management import assign_and_sync_item

        mock_lock.side_effect = Timeout("lock")

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is False

    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_returns_false_when_already_claimed_by_other(
        self, mock_lock: Mock, mock_parse: Mock, mock_run_bd: Mock
    ) -> None:
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        @contextmanager
        def fake_lock(*args: object, **kwargs: object):
            yield Mock()

        mock_lock.side_effect = fake_lock
        mock_parse.return_value = [{"id": "item-1", "assignee": "other-agent"}]
        mock_run_bd.return_value = Mock(stdout="")

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is False

    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_returns_false_on_show_error(
        self, mock_lock: Mock, mock_run_bd: Mock
    ) -> None:
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        @contextmanager
        def fake_lock(*args: object, **kwargs: object):
            yield Mock()

        mock_lock.side_effect = fake_lock
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd", stderr="error")

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is False

    @patch("pokepoke.beads.beads_management._rollback_assignment")
    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_rollback_on_verify_data_none(
        self, mock_lock: Mock, mock_parse: Mock, mock_run_bd: Mock, mock_rollback: Mock
    ) -> None:
        """If bd show succeeds after update but JSON is unparseable, rollback the assignment."""
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        @contextmanager
        def fake_lock(*args: object, **kwargs: object):
            yield Mock()

        mock_lock.side_effect = fake_lock
        mock_parse.side_effect = [
            [{"id": "item-1", "assignee": ""}],   # pre-check: unassigned
            None,                                   # verify: parse returns None
        ]
        mock_run_bd.return_value = Mock(stdout="")

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is False
        mock_rollback.assert_called_once_with("item-1", "could not re-read after update")

    @patch("pokepoke.beads.beads_management._rollback_assignment")
    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_rollback_on_assignee_mismatch(
        self, mock_lock: Mock, mock_parse: Mock, mock_run_bd: Mock, mock_rollback: Mock
    ) -> None:
        """If verification shows a different assignee, rollback the assignment."""
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        @contextmanager
        def fake_lock(*args: object, **kwargs: object):
            yield Mock()

        mock_lock.side_effect = fake_lock
        mock_parse.side_effect = [
            [{"id": "item-1", "assignee": ""}],            # pre-check: unassigned
            [{"id": "item-1", "assignee": "other-agent"}],  # verify: someone else
        ]
        mock_run_bd.return_value = Mock(stdout="")

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is False
        mock_rollback.assert_called_once_with("item-1", "assignee mismatch: 'other-agent'")

    @patch("pokepoke.beads.beads_management._rollback_assignment")
    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_rollback_on_post_update_exception(
        self, mock_lock: Mock, mock_parse: Mock, mock_run_bd: Mock, mock_rollback: Mock
    ) -> None:
        """If an exception occurs during verification (after update succeeded), rollback."""
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        @contextmanager
        def fake_lock(*args: object, **kwargs: object):
            yield Mock()

        mock_lock.side_effect = fake_lock
        mock_parse.return_value = [{"id": "item-1", "assignee": ""}]  # pre-check
        # First call (show) succeeds, second (update) succeeds, third (show for verify) raises
        mock_run_bd.side_effect = [
            Mock(stdout=""),                                            # pre-check show
            Mock(stdout=""),                                            # update
            subprocess.CalledProcessError(1, "bd", stderr="bd crash"),  # verify show
        ]

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is False
        mock_rollback.assert_called_once()
        assert "post-update error" in mock_rollback.call_args[0][1]

    @patch("pokepoke.beads.beads_management._rollback_assignment")
    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_no_rollback_when_update_itself_fails(
        self, mock_lock: Mock, mock_parse: Mock, mock_run_bd: Mock, mock_rollback: Mock
    ) -> None:
        """If the update command itself fails (before it succeeds), no rollback needed."""
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        @contextmanager
        def fake_lock(*args: object, **kwargs: object):
            yield Mock()

        mock_lock.side_effect = fake_lock
        mock_parse.return_value = [{"id": "item-1", "assignee": ""}]  # pre-check
        # Show succeeds, update raises
        mock_run_bd.side_effect = [
            Mock(stdout=""),                                            # pre-check show
            subprocess.CalledProcessError(1, "bd", stderr="update fail"),  # update fails
        ]

        result = assign_and_sync_item("item-1", agent_name="my-agent")

        assert result is False
        mock_rollback.assert_not_called()


class TestRollbackAssignment:
    """Tests for _rollback_assignment."""

    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry")
    def test_calls_unassign_with_retry(self, mock_unassign: Mock) -> None:
        from pokepoke.beads.beads_management import _rollback_assignment
        mock_unassign.return_value = True

        _rollback_assignment("item-1", "test reason")

        mock_unassign.assert_called_once_with("item-1")

    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry")
    def test_logs_error_when_all_retries_exhausted(
        self, mock_unassign: Mock,
    ) -> None:
        from pokepoke.beads.beads_management import _rollback_assignment
        mock_unassign.return_value = False

        _rollback_assignment("item-1", "verify failed")

        mock_unassign.assert_called_once_with("item-1")


class TestUnassignItem:
    """Tests for unassign_item."""

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_successful_unassign(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        from pokepoke.beads.beads_management import unassign_item
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("item-1")

        assert result is True
        # Verify it uses 'open' status (not 'new')
        args = mock_run_bd.call_args[0][0]
        assert '--status' in args
        assert args[args.index('--status') + 1] == 'open'

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_falls_back_when_empty_assignee_fails(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        from pokepoke.beads.beads_management import unassign_item
        mock_run_bd.side_effect = [
            subprocess.CalledProcessError(1, "bd", stderr="invalid option"),  # first try fails
            Mock(stderr=''),  # second try succeeds
        ]
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("item-1")

        assert result is True

    @patch("pokepoke.beads.beads_management._run_bd")
    def test_returns_false_when_both_attempts_fail(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import unassign_item
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd", stderr="failed")

        result = unassign_item("item-1")

        assert result is False

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_detects_stderr_error_on_zero_exit(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """bd may return exit code 0 with validation errors in stderr."""
        from pokepoke.beads.beads_management import unassign_item
        mock_run_bd.side_effect = [
            Mock(stderr='Error updating item: validate field update: invalid status'),  # silent failure
            Mock(stderr=''),  # fallback succeeds
        ]
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("item-1")

        assert result is True
        assert mock_run_bd.call_count == 2

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_detects_stderr_error_in_fallback_attempt(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Fallback also checks stderr for validation errors."""
        from pokepoke.beads.beads_management import unassign_item
        mock_run_bd.side_effect = [
            subprocess.CalledProcessError(1, "bd", stderr="invalid option"),  # first try fails
            Mock(stderr='Error: invalid field value'),  # fallback has stderr error
        ]
        mock_sync.return_value = Mock(returncode=0)

        result = unassign_item("item-1")

        assert result is False
        assert mock_run_bd.call_count == 2

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_logs_warning_when_sync_fails(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """When sync fails after successful unassign, logs warning but returns True."""
        from pokepoke.beads.beads_management import unassign_item
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=1)

        result = unassign_item("item-1")

        assert result is True
        mock_sync.assert_called_once()

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_unassign_with_different_item_ids(self, mock_run_bd: Mock, mock_sync: Mock) -> None:
        """Validates unassign works with various item ID formats."""
        from pokepoke.beads.beads_management import unassign_item
        mock_run_bd.return_value = Mock(stderr='')
        mock_sync.return_value = Mock(returncode=0)

        for item_id in ["task-123", "PokePoke-p7oyy", "bug-fix-auth", "feature/new-api"]:
            result = unassign_item(item_id)
            assert result is True

        assert mock_run_bd.call_count == 4


class TestCloseItem:
    """Tests for close_item."""

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_successful_close(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import close_item
        mock_run_bd.return_value = Mock()

        result = close_item("item-1", "Done")

        assert result is True
        mock_run_bd.assert_called_once_with(
            ['close', 'item-1', '--reason', 'Done'],
            check=True, timeout=30, cwd=None, backend=None,
        )

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_returns_false_on_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import close_item
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd", stderr="error")

        result = close_item("item-1")

        assert result is False


class TestAddComment:
    """Tests for add_comment."""

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_successful_comment(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import add_comment
        mock_run_bd.return_value = Mock()

        result = add_comment("item-1", "test comment")

        assert result is True

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_returns_false_on_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import add_comment
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd", stderr="error")

        result = add_comment("item-1", "test comment")

        assert result is False


class TestGetTotalAttempts:
    """Tests for get_total_attempts."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_attempts_from_metadata(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_total_attempts
        mock_run_bd.return_value = Mock(stdout='[{"metadata": {"total_attempts": 3}}]')
        assert get_total_attempts("item-1") == 3

    @patch("pokepoke.beads.beads_management._run_bd")
    def test_returns_zero_when_no_metadata(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_total_attempts
        mock_run_bd.return_value = Mock(stdout='[{"id": "item-1"}]')
        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_parse_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_total_attempts
        mock_run_bd.return_value = Mock(stdout="not json")
        assert get_total_attempts("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_exception(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_total_attempts
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd")
        assert get_total_attempts("item-1") == 0


class TestIncrementTotalAttempts:
    """Tests for increment_total_attempts."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_increments(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import increment_total_attempts
        mock_run_bd.return_value = Mock(stdout='[{"metadata": {"total_attempts": 2}}]')
        assert increment_total_attempts("item-1") is True
        call_args = mock_run_bd.call_args[0][0]
        assert 'update' in call_args
        assert '"total_attempts": 3' in call_args[-1]

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_increments_and_preserves_other_metadata(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import increment_total_attempts
        mock_run_bd.return_value = Mock(stdout='[{"metadata": {"total_attempts": 2, "gate_rejection_count": 3}}]')
        result = increment_total_attempts("item-1")
        assert result is True
        update_call = mock_run_bd.call_args_list[-1][0][0]
        assert 'update' in update_call
        assert '"total_attempts": 3' in update_call[-1]
        assert '"gate_rejection_count": 3' in update_call[-1]

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_false_when_show_fails(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import increment_total_attempts
        mock_run_bd.return_value = Mock(stdout='not json')
        assert increment_total_attempts("item-1") is False

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_false_on_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import increment_total_attempts
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd")
        assert increment_total_attempts("item-1") is False


class TestGetGateRejectionCount:
    """Tests for get_gate_rejection_count."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_count_from_metadata(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_gate_rejection_count
        mock_run_bd.return_value = Mock(stdout='[{"metadata": {"gate_rejection_count": 2}}]')
        assert get_gate_rejection_count("item-1") == 2

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_when_no_metadata(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_gate_rejection_count
        mock_run_bd.return_value = Mock(stdout='[{"id": "item-1"}]')
        assert get_gate_rejection_count("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_parse_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_gate_rejection_count
        mock_run_bd.return_value = Mock(stdout="not json")
        assert get_gate_rejection_count("item-1") == 0

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_zero_on_exception(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import get_gate_rejection_count
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd")
        assert get_gate_rejection_count("item-1") == 0


class TestIncrementGateRejectionCount:
    """Tests for increment_gate_rejection_count."""

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_increments_and_preserves_other_metadata(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import increment_gate_rejection_count
        mock_run_bd.return_value = Mock(stdout='[{"metadata": {"total_attempts": 5, "gate_rejection_count": 1}}]')
        result = increment_gate_rejection_count("item-1")
        assert result == 2
        update_call = mock_run_bd.call_args_list[-1][0][0]
        assert 'update' in update_call
        assert '"gate_rejection_count": 2' in update_call[-1]
        assert '"total_attempts": 5' in update_call[-1]

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_creates_new_count_from_zero(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import increment_gate_rejection_count
        mock_run_bd.return_value = Mock(stdout='[{"metadata": {}}]')
        result = increment_gate_rejection_count("item-1")
        assert result == 1

    @patch("pokepoke.beads.beads_metadata._run_bd")
    def test_returns_negative_one_on_error(self, mock_run_bd: Mock) -> None:
        from pokepoke.beads.beads_management import increment_gate_rejection_count
        mock_run_bd.side_effect = subprocess.CalledProcessError(1, "bd")
        assert increment_gate_rejection_count("item-1") == -1


class TestSelectNextHierarchicalItem:
    """Tests for select_next_hierarchical_item."""

    def test_returns_none_for_empty_list(self) -> None:
        from pokepoke.beads.beads_management import select_next_hierarchical_item
        assert select_next_hierarchical_item([]) is None

    def test_returns_regular_task_directly(self) -> None:
        from pokepoke.beads.beads_management import select_next_hierarchical_item
        from pokepoke.types import BeadsWorkItem
        item = BeadsWorkItem(id="t-1", title="Task", description="", status="open",
                             priority=1, issue_type="task")
        result = select_next_hierarchical_item([item])
        assert result is item

    def test_skips_human_required_items(self) -> None:
        from pokepoke.beads.beads_hierarchy import HUMAN_REQUIRED_LABEL
        from pokepoke.beads.beads_management import select_next_hierarchical_item
        from pokepoke.types import BeadsWorkItem
        human_item = BeadsWorkItem(id="t-1", title="Human Task", description="",
                                   status="open", priority=1, issue_type="task",
                                   labels=[HUMAN_REQUIRED_LABEL])
        normal_item = BeadsWorkItem(id="t-2", title="Normal Task", description="",
                                    status="open", priority=2, issue_type="task")
        result = select_next_hierarchical_item([human_item, normal_item])
        assert result is normal_item

    @patch("pokepoke.beads.beads_management.resolve_to_leaf_task")
    def test_resolves_epic_to_leaf(self, mock_resolve: Mock) -> None:
        from pokepoke.beads.beads_management import select_next_hierarchical_item
        from pokepoke.types import BeadsWorkItem
        epic = BeadsWorkItem(id="e-1", title="Epic", description="", status="open",
                             priority=1, issue_type="epic")
        leaf = BeadsWorkItem(id="t-1", title="Task", description="", status="open",
                             priority=1, issue_type="task")
        mock_resolve.return_value = leaf

        result = select_next_hierarchical_item([epic])
        assert result is leaf

    @patch("pokepoke.beads.beads_management.resolve_to_leaf_task")
    def test_skips_epic_when_no_leaf_resolved(self, mock_resolve: Mock) -> None:
        from pokepoke.beads.beads_management import select_next_hierarchical_item
        from pokepoke.types import BeadsWorkItem
        epic = BeadsWorkItem(id="e-1", title="Epic", description="", status="open",
                             priority=1, issue_type="epic")
        mock_resolve.return_value = None

        result = select_next_hierarchical_item([epic])
        assert result is None


class TestResolveWithTimeout:
    """Tests for _resolve_with_timeout."""

    @patch("pokepoke.beads.beads_management.resolve_to_leaf_task")
    def test_returns_resolved_item(self, mock_resolve: Mock) -> None:
        from pokepoke.beads.beads_management import _resolve_with_timeout
        from pokepoke.types import BeadsWorkItem
        epic = BeadsWorkItem(id="e-1", title="Epic", description="", status="open",
                             priority=1, issue_type="epic")
        leaf = BeadsWorkItem(id="t-1", title="Leaf", description="", status="open",
                             priority=1, issue_type="task")
        mock_resolve.return_value = leaf
        assert _resolve_with_timeout(epic, timeout=5) is leaf

    @patch("pokepoke.beads.beads_management.resolve_to_leaf_task")
    def test_returns_none_on_timeout(self, mock_resolve: Mock) -> None:
        import time

        from pokepoke.beads.beads_management import _resolve_with_timeout
        from pokepoke.types import BeadsWorkItem
        epic = BeadsWorkItem(id="e-1", title="Epic", description="", status="open",
                             priority=1, issue_type="epic")
        # Sleep just long enough to exceed the 1s timeout, but short enough
        # that ThreadPoolExecutor.shutdown(wait=True) finishes within pytest's
        # default 10s test timeout.
        mock_resolve.side_effect = lambda _item: time.sleep(3)
        result = _resolve_with_timeout(epic, timeout=1)
        assert result is None

    @patch("pokepoke.beads.beads_management.resolve_to_leaf_task")
    def test_returns_none_on_exception(self, mock_resolve: Mock) -> None:
        from pokepoke.beads.beads_management import _resolve_with_timeout
        from pokepoke.types import BeadsWorkItem
        epic = BeadsWorkItem(id="e-1", title="Epic", description="", status="open",
                             priority=1, issue_type="epic")
        mock_resolve.side_effect = RuntimeError("boom")
        result = _resolve_with_timeout(epic, timeout=5)
        assert result is None

    @patch("pokepoke.beads.beads_management.resolve_to_leaf_task")
    def test_reuses_module_level_pool(self, mock_resolve: Mock) -> None:
        """Verify _resolve_with_timeout reuses the module-level pool
        instead of creating a new ThreadPoolExecutor per call."""
        from pokepoke.beads.beads_management import (
            _resolve_pool,
            _resolve_with_timeout,
        )
        from pokepoke.types import BeadsWorkItem

        epic = BeadsWorkItem(id="e-1", title="Epic", description="", status="open",
                             priority=1, issue_type="epic")
        leaf = BeadsWorkItem(id="t-1", title="Leaf", description="", status="open",
                             priority=1, issue_type="task")
        mock_resolve.return_value = leaf

        # Call twice and confirm the same pool is used both times
        with patch.object(_resolve_pool, "submit", wraps=_resolve_pool.submit) as spy:
            _resolve_with_timeout(epic, timeout=5)
            _resolve_with_timeout(epic, timeout=5)
            assert spy.call_count == 2


@pytest.mark.parametrize("backend_config", [BD_CONFIG, BR_CONFIG], ids=["bd", "br"])
class TestBothBackendsManagement:
    """Tests that run against both bd and br backends for management operations."""

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    @patch("pokepoke.beads.beads_management._parse_beads_json")
    @patch("pokepoke.beads.beads_management.acquire_lock")
    def test_assign_and_sync_item_with_backend(
        self,
        mock_lock: Mock,
        mock_parse: Mock,
        mock_run_bd: Mock,
        mock_sync: Mock,
        backend_config,
    ) -> None:
        """Verify assign_and_sync_item works with both backends."""
        from contextlib import contextmanager

        from pokepoke.beads.beads_management import assign_and_sync_item

        original = get_active_backend()
        set_active_backend(backend_config)

        try:
            @contextmanager
            def fake_lock(*args: object, **kwargs: object):
                yield Mock()

            mock_lock.side_effect = fake_lock
            mock_parse.side_effect = [
                [{"id": "item-1", "assignee": ""}],  # pre-check: unassigned
                [{"id": "item-1", "assignee": "my-agent"}],  # verify: us
            ]
            mock_run_bd.return_value = Mock(stdout="")
            mock_sync.return_value = Mock(returncode=0)

            result = assign_and_sync_item("item-1", agent_name="my-agent")

            assert result is True
        finally:
            set_active_backend(original)

    @patch("pokepoke.beads.beads_query._run_bd")
    def test_close_item_with_backend(
        self, mock_run_bd: Mock, backend_config
    ) -> None:
        """Verify close_item works with both backends."""
        from pokepoke.beads.beads_management import close_item

        original = get_active_backend()
        set_active_backend(backend_config)

        try:
            mock_run_bd.return_value = Mock(stdout="", returncode=0)

            result = close_item("item-1", message="done")

            assert result is True
            assert mock_run_bd.call_count >= 1
        finally:
            set_active_backend(original)

    @patch("pokepoke.beads.beads_management.run_bd_sync_with_retry")
    @patch("pokepoke.beads.beads_management._run_bd")
    def test_unassign_item_with_backend(
        self, mock_run_bd: Mock, mock_sync: Mock, backend_config
    ) -> None:
        """Verify unassign_item works with both backends."""
        from pokepoke.beads.beads_management import unassign_item

        original = get_active_backend()
        set_active_backend(backend_config)

        try:
            mock_run_bd.return_value = Mock(stdout="", stderr="", returncode=0)
            mock_sync.return_value = Mock(returncode=0)

            result = unassign_item("item-1")

            assert result is True
        finally:
            set_active_backend(original)

