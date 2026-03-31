"""Tests for session stats registry - thread-safe global stats accessor."""

import threading

from pokepoke.stats.session_stats_registry import (
    get_current_session_stats,
    set_current_session_stats,
)
from pokepoke.types import AgentStats, SessionStats


class TestSessionStatsRegistry:
    """Tests for the global session stats registry."""

    def test_initial_value_is_none(self):
        set_current_session_stats(None)
        assert get_current_session_stats() is None

    def test_set_and_get(self):
        stats = SessionStats(agent_stats=AgentStats())
        set_current_session_stats(stats)

        result = get_current_session_stats()
        assert result is stats

        # Cleanup
        set_current_session_stats(None)

    def test_set_to_none(self):
        stats = SessionStats(agent_stats=AgentStats())
        set_current_session_stats(stats)
        set_current_session_stats(None)

        assert get_current_session_stats() is None

    def test_thread_safety(self):
        """Multiple threads can set/get without error."""
        results = []
        errors = []

        def worker(value):
            try:
                stats = SessionStats(agent_stats=AgentStats(wall_duration=value))
                set_current_session_stats(stats)
                got = get_current_session_stats()
                # We can't assert exact value due to race, but should not crash
                results.append(got is not None)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(float(i),)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert all(results)

        # Cleanup
        set_current_session_stats(None)
