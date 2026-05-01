"""Tests for the warm session pool module."""
import time
from unittest.mock import MagicMock, patch

from pokepoke.config import WarmSessionConfig
from pokepoke.models.warm_session_pool import (
    WarmSession,
    WarmSessionPool,
    get_warm_session_pool,
)


class TestWarmSession:
    """Tests for WarmSession dataclass."""

    def test_age_hours_calculation(self) -> None:
        """Test age calculation in hours."""
        # Create session 1 hour ago
        one_hour_ago = time.time() - 3600
        session = WarmSession(
            session_id="test-session",
            label="test",
            created_at=one_hour_ago,
        )

        age = session.age_hours()
        assert 0.99 < age < 1.01  # Allow small tolerance

    def test_is_expired(self) -> None:
        """Test expiration check."""
        # Create session 2 hours ago
        two_hours_ago = time.time() - 7200
        session = WarmSession(
            session_id="test-session",
            label="test",
            created_at=two_hours_ago,
        )

        # Should be expired with 1 hour max age
        assert session.is_expired(1.0) is True

        # Should not be expired with 4 hour max age
        assert session.is_expired(4.0) is False

    def test_mark_used(self) -> None:
        """Test marking session as used."""
        session = WarmSession(session_id="test", label="test")
        assert session.use_count == 0
        assert session.last_used_at is None

        session.mark_used()

        assert session.use_count == 1
        assert session.last_used_at is not None

        session.mark_used()
        assert session.use_count == 2

class TestWarmSessionPool:
    """Tests for WarmSessionPool class."""

    def test_pool_disabled_by_default(self) -> None:
        """Test that pool is disabled when config says disabled."""
        config = WarmSessionConfig(enabled=False, labels=["test"])
        pool = WarmSessionPool(config)

        assert pool.enabled is False

    def test_pool_enabled_with_labels(self) -> None:
        """Test that pool is enabled with config and labels."""
        config = WarmSessionConfig(enabled=True, labels=["orchestrator", "tests"])
        pool = WarmSessionPool(config)

        assert pool.enabled is True
        assert pool.configured_labels == ["orchestrator", "tests"]

    def test_pool_disabled_without_labels(self) -> None:
        """Test that pool is disabled when no labels configured."""
        config = WarmSessionConfig(enabled=True, labels=[])
        pool = WarmSessionPool(config)

        assert pool.enabled is False

    def test_register_and_get_session(self) -> None:
        """Test registering and retrieving a warm session."""
        config = WarmSessionConfig(enabled=True, labels=["orchestrator"])
        pool = WarmSessionPool(config)

        # Register a session
        session = pool.register_session(
            label="orchestrator",
            session_id="warm-orchestrator-123",
        )

        assert session.session_id == "warm-orchestrator-123"
        assert session.label == "orchestrator"
        assert session.exploration_complete is True

        # Retrieve the session
        retrieved = pool.get_warm_session(["orchestrator"])

        assert retrieved is not None
        assert retrieved.session_id == "warm-orchestrator-123"
        assert retrieved.use_count == 1

    def test_get_session_returns_none_for_no_match(self) -> None:
        """Test that get returns None when no session matches."""
        config = WarmSessionConfig(enabled=True, labels=["orchestrator"])
        pool = WarmSessionPool(config)

        # Register for orchestrator
        pool.register_session(label="orchestrator", session_id="warm-orch-123")

        # Try to get for different label
        result = pool.get_warm_session(["tests", "docs"])

        assert result is None

    def test_get_session_first_match_wins(self) -> None:
        """Test that first matching label wins."""
        config = WarmSessionConfig(enabled=True, labels=["orchestrator", "tests"])
        pool = WarmSessionPool(config)

        pool.register_session(label="orchestrator", session_id="warm-orch-123")
        pool.register_session(label="tests", session_id="warm-tests-456")

        # Request with multiple labels - first match wins
        result = pool.get_warm_session(["tests", "orchestrator"])

        assert result is not None
        assert result.session_id == "warm-tests-456"

    def test_get_session_skips_expired(self) -> None:
        """Test that expired sessions are skipped."""
        config = WarmSessionConfig(enabled=True, labels=["test"], max_age_hours=1.0)
        pool = WarmSessionPool(config)

        # Register an expired session (created 2 hours ago)
        expired_session = WarmSession(
            session_id="warm-expired",
            label="test",
            created_at=time.time() - 7200,
            exploration_complete=True,
        )
        pool._sessions["test"] = [expired_session]

        result = pool.get_warm_session(["test"])

        assert result is None

    def test_get_session_skips_incomplete(self) -> None:
        """Test that incomplete sessions are skipped."""
        config = WarmSessionConfig(enabled=True, labels=["test"])
        pool = WarmSessionPool(config)

        pool.register_session(
            label="test",
            session_id="warm-incomplete",
            exploration_complete=False,
        )

        result = pool.get_warm_session(["test"])

        assert result is None

    def test_get_session_disabled_pool(self) -> None:
        """Test that disabled pool returns None."""
        config = WarmSessionConfig(enabled=False, labels=["test"])
        pool = WarmSessionPool(config)

        pool._sessions["test"] = [
            WarmSession(session_id="warm-test", label="test", exploration_complete=True)
        ]

        result = pool.get_warm_session(["test"])

        assert result is None

    def test_get_session_empty_labels(self) -> None:
        """Test that empty labels list returns None."""
        config = WarmSessionConfig(enabled=True, labels=["test"])
        pool = WarmSessionPool(config)

        pool.register_session(label="test", session_id="warm-test")

        assert pool.get_warm_session([]) is None
        assert pool.get_warm_session(None) is None

    def test_invalidate_all(self) -> None:
        """Test invalidating all sessions."""
        config = WarmSessionConfig(enabled=True, labels=["a", "b"])
        pool = WarmSessionPool(config)

        pool.register_session(label="a", session_id="warm-a")
        pool.register_session(label="b", session_id="warm-b")

        count = pool.invalidate_all()

        assert count == 2
        assert pool.get_warm_session(["a"]) is None
        assert pool.get_warm_session(["b"]) is None

    def test_pool_size_limit(self) -> None:
        """Test that pool respects size limit per label."""
        config = WarmSessionConfig(
            enabled=True, labels=["test"], pool_size_per_label=2
        )
        pool = WarmSessionPool(config)

        pool.register_session(label="test", session_id="session-1")
        pool.register_session(label="test", session_id="session-2")
        pool.register_session(label="test", session_id="session-3")

        # Should only have 2 sessions (oldest evicted)
        assert len(pool._sessions["test"]) == 2
        session_ids = {s.session_id for s in pool._sessions["test"]}
        assert "session-1" not in session_ids
        assert "session-2" in session_ids
        assert "session-3" in session_ids

    def test_mark_warming_in_progress(self) -> None:
        """Test warming-in-progress flag prevents duplicates."""
        config = WarmSessionConfig(enabled=True, labels=["test"])
        pool = WarmSessionPool(config)

        # First call should succeed
        assert pool.mark_warming_in_progress("test") is True

        # Second call should fail (already in progress)
        assert pool.mark_warming_in_progress("test") is False

        # Clear and try again
        pool.clear_warming_in_progress("test")
        assert pool.mark_warming_in_progress("test") is True

    def test_get_labels_needing_warmup(self) -> None:
        """Test identifying labels that need warming."""
        config = WarmSessionConfig(
            enabled=True, labels=["a", "b", "c"], pool_size_per_label=1
        )
        pool = WarmSessionPool(config)

        # Only register for "a"
        pool.register_session(label="a", session_id="warm-a")

        needs = pool.get_labels_needing_warmup()

        assert "a" not in needs
        assert "b" in needs
        assert "c" in needs

    def test_get_labels_needing_warmup_skips_in_progress(self) -> None:
        """Test that warming-in-progress labels are skipped."""
        config = WarmSessionConfig(enabled=True, labels=["a", "b"])
        pool = WarmSessionPool(config)

        pool.mark_warming_in_progress("a")

        needs = pool.get_labels_needing_warmup()

        assert "a" not in needs
        assert "b" in needs

    def test_get_stats(self) -> None:
        """Test statistics reporting."""
        config = WarmSessionConfig(enabled=True, labels=["a", "b"], pool_size_per_label=3)
        pool = WarmSessionPool(config)

        pool.register_session(label="a", session_id="warm-a-1")
        pool.register_session(label="a", session_id="warm-a-2")
        pool.register_session(label="b", session_id="warm-b")
        pool.mark_warming_in_progress("c")

        stats = pool.get_stats()

        assert stats["total_sessions"] == 3
        assert stats["valid_sessions"] == 3
        assert stats["warming_in_progress"] == 1
        assert stats["configured_labels"] == 2
        assert stats["per_label"]["a"] == 2
        assert stats["per_label"]["b"] == 1

    def test_label_case_insensitive(self) -> None:
        """Test that labels are case-insensitive."""
        config = WarmSessionConfig(enabled=True, labels=["Orchestrator"])
        pool = WarmSessionPool(config)

        pool.register_session(label="ORCHESTRATOR", session_id="warm-orch")

        # Should match regardless of case
        result = pool.get_warm_session(["orchestrator"])
        assert result is not None
        assert result.session_id == "warm-orch"

class TestGlobalPool:
    """Tests for the global pool singleton."""

    def test_get_warm_session_pool_creates_singleton(self) -> None:
        """Test that get_warm_session_pool returns consistent instance."""

        with patch("pokepoke.config.get_config") as mock_config:
            mock_config.return_value = MagicMock(
                warm_sessions=WarmSessionConfig(enabled=True, labels=["test"])
            )

            pool1 = get_warm_session_pool()
            pool2 = get_warm_session_pool()

            assert pool1 is pool2

    def teardown_method(self) -> None:
        """Reset global pool after each test."""
