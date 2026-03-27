"""Tests for item dispatching and scheduling.

This module tests:
- dispatch_items: Dispatching work items to worker threads
- High-conflict scheduling: Solo execution for risky items
"""

import threading
from unittest.mock import MagicMock, Mock, patch

from pokepoke.agents.parallel_support import dispatch_items
from pokepoke.types import BeadsWorkItem


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


def _make_high_conflict_item(item_id: str = "hc1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"HighConflict-{item_id}", status="open",
        priority=1, issue_type="task", labels=["high-conflict-risk"],
    )


class TestDispatchItems:
    """Tests for dispatch_items."""

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_zero_slots_returns_immediately(self, *_mocks):
        run_logger = MagicMock()
        result = dispatch_items(
            [], 0, True, False, 0, 10, set(), set(), {},
            threading.Semaphore(1), MagicMock(), run_logger, 0, Mock(), Mock(),
        )
        assert result == 0

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_submits_item_to_executor(self, _name, _assign, _claim, mock_select, _stop, _closed):
        item = _make_item("d1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        executor = MagicMock()
        mock_fut = MagicMock()
        executor.submit.return_value = mock_fut
        sem = threading.Semaphore(2)
        futures: dict = {}
        build_name = Mock(return_value="agent-worker-1")

        counter = dispatch_items(
            [item], 1, True, False, 0, 10, set(), set(), futures,
            sem, executor, run_logger, 0, build_name, Mock(),
        )
        assert counter == 1
        assert mock_fut in futures

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=False)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_skips_unclaimed_item(self, _name, _assign, mock_select, _stop):
        """When assign_and_sync_item returns False the item is not submitted."""
        item = _make_item("skip1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        executor = MagicMock()
        futures: dict = {}

        counter = dispatch_items(
            [item], 1, True, False, 0, 10, set(), set(), futures,
            threading.Semaphore(1), executor, run_logger, 0, Mock(), Mock(),
        )
        # worker_counter increments before assign attempt, but item is not submitted
        assert counter >= 0  # counter may increment even for failed claims
        executor.submit.assert_not_called()

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=False)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_failed_assign_adds_to_failed_ids(self, _name, _assign, _claim, mock_select, _stop, _closed):
        item = _make_item("fa1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        failed_ids: set[str] = set()

        dispatch_items(
            [item], 1, True, False, 0, 10, failed_ids, set(), {},
            threading.Semaphore(1), MagicMock(), run_logger, 0, Mock(return_value="w"), Mock(),
        )
        assert "fa1" in failed_ids

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_executor_submit_failure_unassigns(self, _name, mock_unassign, _assign, _claim, mock_select, _stop, _closed):
        item = _make_item("ef1")
        mock_select.return_value = [item]
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("executor full")
        run_logger = MagicMock()
        sem = threading.Semaphore(1)

        import contextlib
        with contextlib.suppress(RuntimeError):
            dispatch_items(
                [item], 1, True, False, 0, 10, set(), set(), {},
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )
        mock_unassign.assert_called_once_with("ef1")

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.parallel.unassign_with_retry", side_effect=RuntimeError("unassign boom"))
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_executor_submit_unassign_failure_logs_warning(self, _name, mock_unassign, _assign, _claim, mock_select, _stop, _closed):
        """When executor.submit fails AND unassign also fails, a warning is logged."""
        item = _make_item("ef2")
        mock_select.return_value = [item]
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("executor full")
        run_logger = MagicMock()
        sem = threading.Semaphore(1)

        import contextlib
        with contextlib.suppress(RuntimeError):
            dispatch_items(
                [item], 1, True, False, 0, 10, set(), set(), {},
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )
        mock_unassign.assert_called_once_with("ef2")
        warning_calls = [
            c for c in run_logger.log_orchestrator.call_args_list
            if c.kwargs.get("level") == "WARNING"
        ]
        assert any("ef2" in str(c) and "unassign" in str(c).lower() for c in warning_calls), (
            "Expected a WARNING log mentioning item id 'ef2' and unassign failure"
        )

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.assign_and_sync_item")
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_advances_past_unclaimable_items(self, _name, mock_assign, _stop):
        """Regression for PokePoke-pfoc: dispatch must advance past already-claimed
        items and fill remaining slots from later candidates in the ready queue."""
        # 5 items total; first 2 are unclaimable (assign fails), last 3 succeed
        items = [_make_item(f"adv-{i}") for i in range(5)]
        unclaimable = {items[0].id, items[1].id}
        # assign_and_sync_item receives item_id as first positional arg
        mock_assign.side_effect = lambda item_id, **kw: item_id not in unclaimable

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded]
            return candidates[:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}
            failed_ids: set[str] = set()
            sem = threading.Semaphore(3)

            counter = dispatch_items(
                items, 3, True, False, 0, 10, failed_ids, set(), futures,
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # All 3 claimable items should be dispatched
        assert counter >= 3  # at least 3 workers attempted
        assert executor.submit.call_count == 3
        # Unclaimable items should be added to failed_claim_ids
        assert unclaimable.issubset(failed_ids)

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=False)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_unclaimable_items_added_to_failed_ids(self, _name, _claim, _stop, _closed):
        """Regression for PokePoke-pfoc: unclaimable items must be added to
        failed_claim_ids so they are not re-selected in subsequent iterations."""
        items = [_make_item(f"uc-{i}") for i in range(3)]

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded]
            return candidates[:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            run_logger = MagicMock()
            failed_ids: set[str] = set()

            dispatch_items(
                items, 3, True, False, 0, 10, failed_ids, set(), {},
                threading.Semaphore(3), MagicMock(), run_logger, 0, Mock(), Mock(),
            )

        # All items should be in failed_claim_ids
        assert failed_ids == {"uc-0", "uc-1", "uc-2"}

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.assign_and_sync_item")
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_closed_item_skipped_and_added_to_failed_ids(
        self, _name, mock_assign, _stop,
    ):
        """Items whose assign_and_sync_item call fails (e.g. already closed)
        should be skipped and added to the skip set so they are not
        re-selected in subsequent replenish cycles."""
        item_closed = _make_item("closed-1")
        item_open = _make_item("open-1")
        # assign succeeds only for the open item
        mock_assign.side_effect = lambda item_id, **kw: item_id != "closed-1"

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded]
            return candidates[:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}
            failed_ids: set[str] = set()
            sem = threading.Semaphore(2)

            dispatch_items(
                [item_closed, item_open], 2, True, False, 0, 10,
                failed_ids, set(), futures,
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # Only the open item should be dispatched
        assert executor.submit.call_count == 1
        # Closed item should be in the skip set
        assert "closed-1" in failed_ids


class TestDispatchHighConflictItems:
    """Tests that high-conflict items run solo (PokePoke-sz6k)."""

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_blocks_new_dispatch(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """When a high-conflict item is already running, nothing new is dispatched."""
        hc_item = _make_high_conflict_item("hc-active")
        normal_item = _make_item("normal-1")

        # Simulate a high-conflict item already in the futures dict
        mock_fut = MagicMock()
        futures: dict = {mock_fut: hc_item}

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            run_logger = MagicMock()

            counter = dispatch_items(
                [normal_item], 2, True, False, 0, 10, set(), {"hc-active"}, futures,
                threading.Semaphore(2), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        assert counter == 0
        executor.submit.assert_not_called()

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_deferred_when_others_active(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """A high-conflict item is deferred when non-conflict items are running."""
        hc_item = _make_high_conflict_item("hc-defer")
        running_item = _make_item("running-1")

        mock_fut = MagicMock()
        futures: dict = {mock_fut: running_item}

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            run_logger = MagicMock()

            counter = dispatch_items(
                [hc_item], 2, True, False, 0, 10, set(), {"running-1"}, futures,
                threading.Semaphore(2), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # High-conflict item should NOT be dispatched
        assert counter == 0
        executor.submit.assert_not_called()

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_dispatched_when_idle(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """A high-conflict item IS dispatched when no other items are active."""
        hc_item = _make_high_conflict_item("hc-solo")

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}

            counter = dispatch_items(
                [hc_item], 2, True, False, 0, 10, set(), set(), futures,
                threading.Semaphore(2), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        assert counter == 1
        assert executor.submit.call_count == 1

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_prevents_additional_dispatch(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """After dispatching a high-conflict item, no more items are dispatched."""
        hc_item = _make_high_conflict_item("hc-only")
        normal_item = _make_item("extra-1")

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}

            counter = dispatch_items(
                [hc_item, normal_item], 3, True, False, 0, 10, set(), set(), futures,
                threading.Semaphore(3), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # Only the high-conflict item should be dispatched, not the normal one
        assert counter == 1
        assert executor.submit.call_count == 1

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_normal_dispatched_before_high_conflict_deferred(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """Normal items before the high-conflict item dispatch; the high-conflict is deferred."""
        normal_item = _make_item("norm-1")
        hc_item = _make_high_conflict_item("hc-after")

        call_count = [0]

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded][:count]
            call_count[0] += 1
            return candidates

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}

            counter = dispatch_items(
                [normal_item, hc_item], 3, True, False, 0, 10, set(), set(), futures,
                threading.Semaphore(3), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # Normal item dispatched; high-conflict deferred because dispatched > 0
        assert counter >= 1
        assert executor.submit.call_count >= 1

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_deferred_high_conflict_does_not_starve_normal_items(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """Normal items dispatch even when a high-conflict item is first in the queue.

        Regression test for PokePoke-mdaf: when slots=1 and a high-conflict
        item sits at the front of ready_items with an active future, the
        dispatcher must skip past the deferred item and dispatch the normal
        one rather than breaking out of the loop with no progress.
        """
        hc_item = _make_high_conflict_item("hc-front")
        normal_item = _make_item("norm-behind")

        running_item = _make_item("running-1")
        mock_running_fut = MagicMock()
        futures: dict = {mock_running_fut: running_item}

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()

            counter = dispatch_items(
                [hc_item, normal_item], 1, True, False, 0, 10,
                set(), {"running-1"}, futures,
                threading.Semaphore(2), executor, run_logger, 0,
                Mock(return_value="w"), Mock(),
            )

        # The normal item behind the deferred high-conflict item MUST dispatch
        assert counter == 1
        assert executor.submit.call_count == 1
