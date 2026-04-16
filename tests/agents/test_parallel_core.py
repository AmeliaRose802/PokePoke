"""Comprehensive unit tests for parallel orchestration core functions.

Tests for parallel processing, agent spawning, and pool management.
"""

import concurrent.futures
import threading
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.agents.parallel import (
    _build_worker_name,
    _collect_done_futures,
    _hash_string,
    _parallel_process_item,
    _snake_for_work_item,
    get_effective_max_agents,
    request_spawn_agent,
)
from pokepoke.types import BeadsWorkItem, WorkItemResult
from pokepoke.utils.logging_utils import RunLogger


class TestGetEffectiveMaxAgents:
    """Tests for get_effective_max_agents function."""

    @patch('pokepoke.agents.parallel.compute_effective_max_agents')
    def test_get_effective_max_agents_calls_compute(self, mock_compute) -> None:
        """get_effective_max_agents delegates to compute_effective_max_agents."""
        mock_compute.return_value = 4

        result = get_effective_max_agents()

        assert result == 4
        mock_compute.assert_called_once()
        # Should get at least 1
        call_arg = mock_compute.call_args[0][0]
        assert call_arg >= 1

    @patch('pokepoke.agents.parallel.compute_effective_max_agents')
    def test_get_effective_max_agents_returns_positive(self, mock_compute) -> None:
        """Result is always at least 1."""
        mock_compute.return_value = 1

        result = get_effective_max_agents()

        assert result >= 1


class TestHashString:
    """Tests for _hash_string deterministic hash function."""

    def test_hash_string_deterministic(self) -> None:
        """Hash function produces same result for same input."""
        hash1 = _hash_string("test-id-123")
        hash2 = _hash_string("test-id-123")

        assert hash1 == hash2

    def test_hash_string_different_inputs(self) -> None:
        """Different inputs produce different hashes."""
        hash1 = _hash_string("test-id-1")
        hash2 = _hash_string("test-id-2")

        assert hash1 != hash2

    def test_hash_string_returns_positive(self) -> None:
        """Hash function returns positive integer."""
        result = _hash_string("test-id")

        assert isinstance(result, int)
        assert result >= 0

    def test_hash_string_empty_string(self) -> None:
        """Handle empty string."""
        result = _hash_string("")

        assert isinstance(result, int)
        assert result >= 0

    def test_hash_string_special_characters(self) -> None:
        """Handle special characters."""
        result = _hash_string("test@#$%^&*()")

        assert isinstance(result, int)
        assert result >= 0

    def test_hash_string_unicode(self) -> None:
        """Handle unicode characters."""
        result = _hash_string("test-🐍-emoji")

        assert isinstance(result, int)
        assert result >= 0


class TestSnakeForWorkItem:
    """Tests for _snake_for_work_item function."""

    def test_snake_for_work_item_deterministic(self) -> None:
        """Returns same snake type for same item ID."""
        snake1 = _snake_for_work_item("task-123")
        snake2 = _snake_for_work_item("task-123")

        assert snake1 == snake2

    def test_snake_for_work_item_valid_types(self) -> None:
        """Only returns valid snake types."""
        valid_snakes = ("cobra", "corn", "rainbow_boa", "rattlesnake", "sea_snake")

        result = _snake_for_work_item("task-456")

        assert result in valid_snakes

    def test_snake_for_work_item_distribution(self) -> None:
        """Multiple item IDs produce variety of snakes."""
        snakes = set()
        for i in range(100):
            snake = _snake_for_work_item(f"task-{i}")
            snakes.add(snake)

        # Should have at least 2-3 different snakes out of 5
        assert len(snakes) >= 2


class TestBuildWorkerName:
    """Tests for _build_worker_name function."""

    def test_build_worker_name_includes_base_name(self) -> None:
        """Worker name includes base agent name."""
        result = _build_worker_name("TestAgent", "item-1", 1)

        assert "TestAgent" in result

    def test_build_worker_name_includes_snake_type(self) -> None:
        """Worker name includes snake type."""
        result = _build_worker_name("TestAgent", "item-1", 1)

        valid_snakes = ("cobra", "corn", "rainbow_boa", "rattlesnake", "sea_snake")
        has_snake = any(snake in result for snake in valid_snakes)
        assert has_snake

    def test_build_worker_name_includes_counter(self) -> None:
        """Worker name includes counter."""
        result = _build_worker_name("TestAgent", "item-1", 42)

        assert "42" in result

    def test_build_worker_name_deterministic_for_same_item(self) -> None:
        """Same item ID produces same snake type."""
        name1 = _build_worker_name("Agent", "task-1", 1)
        name2 = _build_worker_name("Agent", "task-1", 2)

        # Extract snake type (should be same for same item ID)
        valid_snakes = ("cobra", "corn", "rainbow_boa", "rattlesnake", "sea_snake")
        snake1 = next(s for s in valid_snakes if s in name1)
        snake2 = next(s for s in valid_snakes if s in name2)

        assert snake1 == snake2


class TestParallelProcessItem:
    """Tests for _parallel_process_item function."""

    def _make_work_item(self, item_id: str = "test-1") -> BeadsWorkItem:
        return BeadsWorkItem(
            id=item_id,
            title="Test Item",
            status="ready",
            priority=1,
            issue_type="task",
        )

    @patch('pokepoke.agents.parallel.terminal_ui')
    @patch('pokepoke.agents.parallel.process_work_item')
    @patch('pokepoke.agents.parallel.clear_agent_name')
    def test_parallel_process_item_success(
        self,
        mock_clear_agent,
        mock_process,
        mock_ui,
    ) -> None:
        """Successfully process work item."""
        item = self._make_work_item()
        mock_process.return_value = WorkItemResult(success=True, request_count=1)
        mock_ui.ui.agent_output_for = MagicMock()
        mock_ui.ui.agent_output_for.return_value.__enter__ = Mock(return_value=None)
        mock_ui.ui.agent_output_for.return_value.__exit__ = Mock(return_value=None)

        run_logger = Mock(spec=RunLogger)
        semaphore = threading.Semaphore(1)

        result = _parallel_process_item(item, run_logger, semaphore)

        assert result.success is True
        mock_process.assert_called_once()
        mock_clear_agent.assert_called_once()

    @patch('pokepoke.agents.parallel.terminal_ui')
    @patch('pokepoke.agents.parallel.process_work_item')
    @patch('pokepoke.agents.parallel.clear_agent_name')
    def test_parallel_process_item_failure(
        self,
        mock_clear_agent,
        mock_process,
        mock_ui,
    ) -> None:
        """Handle failed work item processing."""
        item = self._make_work_item()
        mock_process.return_value = WorkItemResult(success=False, request_count=0)
        mock_ui.ui.agent_output_for = MagicMock()
        mock_ui.ui.agent_output_for.return_value.__enter__ = Mock(return_value=None)
        mock_ui.ui.agent_output_for.return_value.__exit__ = Mock(return_value=None)

        run_logger = Mock(spec=RunLogger)
        semaphore = threading.Semaphore(1)

        result = _parallel_process_item(item, run_logger, semaphore)

        assert result.success is False

    @patch('pokepoke.agents.parallel.terminal_ui')
    @patch('pokepoke.agents.parallel.process_work_item')
    @patch('pokepoke.agents.parallel.clear_agent_name')
    def test_parallel_process_item_exception(
        self,
        mock_clear_agent,
        mock_process,
        mock_ui,
    ) -> None:
        """Handle exception during work item processing."""
        item = self._make_work_item()
        mock_process.side_effect = RuntimeError("Processing failed")
        mock_ui.ui.agent_output_for = MagicMock()
        mock_ui.ui.agent_output_for.return_value.__enter__ = Mock(return_value=None)
        mock_ui.ui.agent_output_for.return_value.__exit__ = Mock(return_value=None)

        run_logger = Mock(spec=RunLogger)
        semaphore = threading.Semaphore(1)

        with pytest.raises(RuntimeError, match="Processing failed"):
            _parallel_process_item(item, run_logger, semaphore)

        # Should release semaphore even on exception
        mock_clear_agent.assert_called_once()

    @patch('pokepoke.agents.parallel.terminal_ui')
    @patch('pokepoke.agents.parallel.process_work_item')
    @patch('pokepoke.agents.parallel.set_agent_name')
    @patch('pokepoke.agents.parallel.clear_agent_name')
    def test_parallel_process_item_with_worker_name(
        self,
        mock_clear_agent,
        mock_set_agent,
        mock_process,
        mock_ui,
    ) -> None:
        """Set agent name when worker name provided."""
        item = self._make_work_item()
        mock_process.return_value = WorkItemResult(success=True, request_count=1)
        mock_ui.ui.agent_output_for = MagicMock()
        mock_ui.ui.agent_output_for.return_value.__enter__ = Mock(return_value=None)
        mock_ui.ui.agent_output_for.return_value.__exit__ = Mock(return_value=None)

        run_logger = Mock(spec=RunLogger)
        semaphore = threading.Semaphore(1)
        worker_name = "agent-worker-1"

        _parallel_process_item(item, run_logger, semaphore, worker_agent_name=worker_name)

        mock_set_agent.assert_called_once_with(worker_name)


class TestCollectDoneFutures:
    """Tests for _collect_done_futures function."""

    def _make_work_item(self, item_id: str = "test-1") -> BeadsWorkItem:
        return BeadsWorkItem(
            id=item_id,
            title="Test Item",
            status="ready",
            priority=1,
            issue_type="task",
        )

    def test_collect_done_futures_no_futures_done(self) -> None:
        """Handle case where no futures are done."""
        futures = {}
        failed_claim_ids = set()
        session_stats = Mock()
        run_logger = Mock(spec=RunLogger)
        record_fn = Mock()

        total, any_success, _s, _f = _collect_done_futures(
            futures, failed_claim_ids, 0, session_stats, run_logger, record_fn
        )

        assert total == 0
        assert any_success is False

    def test_collect_done_futures_uses_nonblocking_polling(self) -> None:
        """Verify that collect_done_futures uses non-blocking .done() polling instead of wait().

        The fix for PokePoke-82v1j removed concurrent.futures.wait() which could hang
        indefinitely. This test verifies the function never calls wait() and instead
        relies solely on non-blocking .done() checks.
        """
        future = Mock(spec=concurrent.futures.Future)
        future.done.return_value = False
        item = self._make_work_item()

        futures = {future: item}
        failed_claim_ids = set()
        session_stats = Mock()
        run_logger = Mock(spec=RunLogger)
        record_fn = Mock()

        # Call collect_done_futures - it should return immediately without calling wait()
        with patch('concurrent.futures.wait') as mock_wait:
            _collect_done_futures(
                futures, failed_claim_ids, 0, session_stats, run_logger, record_fn
            )
            # Verify wait() was never called
            mock_wait.assert_not_called()

        # Verify that .done() was called for non-blocking polling
        future.done.assert_called()

    def test_collect_done_futures_records_successful_result(self) -> None:
        """Record successful work item result."""
        future = Mock(spec=concurrent.futures.Future)
        future.done.return_value = True
        future.result.return_value = WorkItemResult(success=True, request_count=5)
        item = self._make_work_item("task-1")

        futures = {future: item}
        failed_claim_ids = set()
        session_stats = Mock()
        run_logger = Mock(spec=RunLogger)
        record_fn = Mock()

        total, any_success, _s, _f = _collect_done_futures(
            futures, failed_claim_ids, 0, session_stats, run_logger, record_fn
        )

        assert total == 5
        assert any_success is True
        record_fn.assert_called_once()
        assert "task-1" not in failed_claim_ids  # Discarded from failed set

    def test_collect_done_futures_records_failed_claim_result(self) -> None:
        """Track failed claim attempts."""
        future = Mock(spec=concurrent.futures.Future)
        future.done.return_value = True
        future.result.return_value = WorkItemResult(success=False, request_count=0)
        item = self._make_work_item("task-2")

        futures = {future: item}
        failed_claim_ids = set()
        session_stats = Mock()
        run_logger = Mock(spec=RunLogger)
        record_fn = Mock()

        total, any_success, _s, _f = _collect_done_futures(
            futures, failed_claim_ids, 0, session_stats, run_logger, record_fn
        )

        assert total == 0
        assert any_success is False
        assert "task-2" in failed_claim_ids  # Added to failed set

    def test_collect_done_futures_handles_exception(self) -> None:
        """Handle exceptions from future results."""
        future = Mock(spec=concurrent.futures.Future)
        future.done.return_value = True
        future.result.side_effect = RuntimeError("Execution error")
        item = self._make_work_item("task-3")

        futures = {future: item}
        failed_claim_ids = set()
        session_stats = Mock()
        run_logger = Mock(spec=RunLogger)
        record_fn = Mock()

        _total, _any_success, _s, _f = _collect_done_futures(
            futures, failed_claim_ids, 0, session_stats, run_logger, record_fn
        )

        # Exception should not add to failed_claim_ids (was_exception flag)
        assert "task-3" not in failed_claim_ids

    def test_collect_done_futures_record_fn_exception(self) -> None:
        """Handle exceptions from record_fn."""
        future = Mock(spec=concurrent.futures.Future)
        future.done.return_value = True
        future.result.return_value = WorkItemResult(success=True, request_count=1)
        item = self._make_work_item("task-4")

        futures = {future: item}
        failed_claim_ids = set()
        session_stats = Mock()
        run_logger = Mock(spec=RunLogger)
        record_fn = Mock(side_effect=OSError("Recording failed"))

        # Should not raise, log error instead
        total, _any_success, _s, _f = _collect_done_futures(
            futures, failed_claim_ids, 0, session_stats, run_logger, record_fn
        )

        assert total == 1

    def test_collect_done_futures_accumulates_request_count(self) -> None:
        """Accumulate request counts from multiple futures."""
        future1 = Mock(spec=concurrent.futures.Future)
        future1.done.return_value = True
        future1.result.return_value = WorkItemResult(success=True, request_count=5)

        future2 = Mock(spec=concurrent.futures.Future)
        future2.done.return_value = True
        future2.result.return_value = WorkItemResult(success=True, request_count=3)

        item1 = self._make_work_item("task-1")
        item2 = self._make_work_item("task-2")

        futures = {future1: item1, future2: item2}
        failed_claim_ids = set()
        session_stats = Mock()
        run_logger = Mock(spec=RunLogger)
        record_fn = Mock()

        total, any_success, _s, _f = _collect_done_futures(
            futures, failed_claim_ids, 0, session_stats, run_logger, record_fn
        )

        assert total == 8  # 5 + 3
        assert any_success is True


class TestRequestSpawnAgent:
    """Tests for request_spawn_agent function."""

    @patch('pokepoke.agents.parallel._spawn_wakeup')
    def test_request_spawn_agent_signals_wakeup(self, mock_event) -> None:
        """Signal the wakeup event."""
        request_spawn_agent()

        mock_event.set.assert_called_once()
