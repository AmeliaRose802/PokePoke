"""Warm session pool for pre-created SDK sessions with codebase context.

This module provides a pool of pre-warmed Copilot SDK sessions that have already
explored the codebase for common work types. When a work item arrives with a
matching label, the orchestrator can use a warm session that already knows the
module layout instead of starting cold exploration.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.config import WarmSessionConfig

logger = logging.getLogger(__name__)


@dataclass
class WarmSession:
    """Metadata for a pre-warmed SDK session."""

    session_id: str
    label: str
    created_at: float = field(default_factory=time.time)
    last_used_at: float | None = None
    exploration_complete: bool = False
    use_count: int = 0

    def age_hours(self) -> float:
        """Return the age of this session in hours."""
        return (time.time() - self.created_at) / 3600.0

    def is_expired(self, max_age_hours: float) -> bool:
        """Check if this session has exceeded the max age."""
        return self.age_hours() > max_age_hours

    def mark_used(self) -> None:
        """Mark this session as used."""
        self.last_used_at = time.time()
        self.use_count += 1


class WarmSessionPool:
    """Thread-safe pool of pre-warmed SDK sessions keyed by label.

    Usage::

        pool = WarmSessionPool(config)
        await pool.warm_up()  # Called at orchestrator startup

        # When dispatching a work item
        session = pool.get_warm_session(work_item.labels)
        if session:
            # Use session.session_id for SDK resume
            ...
        else:
            # Fall back to cold start
            ...

        # After merges or periodically
        pool.invalidate_all()
    """

    def __init__(self, config: WarmSessionConfig) -> None:
        """Initialize the pool with configuration."""
        self._config = config
        self._lock = threading.Lock()
        # Map: label -> list of WarmSession (multiple sessions per label for pool_size > 1)
        self._sessions: dict[str, list[WarmSession]] = {}
        self._warming_in_progress: set[str] = set()

    @property
    def enabled(self) -> bool:
        """Check if warm sessions are enabled."""
        return self._config.enabled and len(self._config.labels) > 0

    @property
    def configured_labels(self) -> list[str]:
        """Get the list of labels configured for warm sessions."""
        return list(self._config.labels)

    def get_warm_session(self, labels: list[str] | None) -> WarmSession | None:
        """Find a warm session matching any of the given labels.

        Args:
            labels: Labels from the work item (checked in order).

        Returns:
            A warm session if one matches and is valid, None otherwise.
        """
        if not self.enabled or not labels:
            return None

        with self._lock:
            for label in labels:
                label_lower = label.lower()
                sessions = self._sessions.get(label_lower, [])
                for session in sessions:
                    if session.exploration_complete and not session.is_expired(
                        self._config.max_age_hours
                    ):
                        session.mark_used()
                        logger.info(
                            f"🔥 Using warm session for label '{label}': "
                            f"{session.session_id} (age: {session.age_hours():.1f}h, "
                            f"uses: {session.use_count})"
                        )
                        return session

        return None

    def register_session(
        self,
        label: str,
        session_id: str,
        exploration_complete: bool = True,
    ) -> WarmSession:
        """Register a new warm session for a label.

        Args:
            label: The label/code-area this session covers.
            session_id: The SDK session ID.
            exploration_complete: Whether the exploration phase finished.

        Returns:
            The created WarmSession object.
        """
        session = WarmSession(
            session_id=session_id,
            label=label.lower(),
            exploration_complete=exploration_complete,
        )

        with self._lock:
            label_lower = label.lower()
            if label_lower not in self._sessions:
                self._sessions[label_lower] = []

            # Respect pool size limit per label
            sessions = self._sessions[label_lower]
            while len(sessions) >= self._config.pool_size_per_label:
                oldest = min(sessions, key=lambda s: s.created_at)
                sessions.remove(oldest)
                logger.debug(f"Evicted oldest warm session for '{label}': {oldest.session_id}")

            sessions.append(session)
            self._warming_in_progress.discard(label_lower)

        logger.info(
            f"🔥 Registered warm session for label '{label}': {session_id}"
        )
        return session

    def mark_warming_in_progress(self, label: str) -> bool:
        """Mark a label as currently being warmed (to prevent duplicates).

        Returns:
            True if this call marked it (caller should warm), False if already in progress.
        """
        with self._lock:
            label_lower = label.lower()
            if label_lower in self._warming_in_progress:
                return False
            self._warming_in_progress.add(label_lower)
            return True

    def clear_warming_in_progress(self, label: str) -> None:
        """Clear the warming-in-progress flag for a label."""
        with self._lock:
            self._warming_in_progress.discard(label.lower())

    def invalidate_label(self, label: str) -> int:
        """Invalidate all sessions for a specific label.

        Args:
            label: The label to invalidate.

        Returns:
            Number of sessions invalidated.
        """
        with self._lock:
            label_lower = label.lower()
            sessions = self._sessions.pop(label_lower, [])
            count = len(sessions)

        if count > 0:
            logger.info(f"🗑️  Invalidated {count} warm session(s) for label '{label}'")
        return count

    def invalidate_all(self) -> int:
        """Invalidate all warm sessions (e.g., after a merge changes codebase).

        Returns:
            Total number of sessions invalidated.
        """
        with self._lock:
            total = sum(len(sessions) for sessions in self._sessions.values())
            self._sessions.clear()
            self._warming_in_progress.clear()

        if total > 0:
            logger.info(f"🗑️  Invalidated all {total} warm session(s)")
        return total

    def invalidate_expired(self) -> int:
        """Remove expired sessions from the pool.

        Returns:
            Number of sessions removed.
        """
        removed = 0
        max_age = self._config.max_age_hours

        with self._lock:
            for label, sessions in list(self._sessions.items()):
                expired = [s for s in sessions if s.is_expired(max_age)]
                for session in expired:
                    sessions.remove(session)
                    removed += 1
                    logger.debug(
                        f"Removed expired warm session for '{label}': "
                        f"{session.session_id} (age: {session.age_hours():.1f}h)"
                    )
                if not sessions:
                    del self._sessions[label]

        if removed > 0:
            logger.info(f"🧹 Removed {removed} expired warm session(s)")
        return removed

    def get_labels_needing_warmup(self) -> list[str]:
        """Get labels that are configured but don't have valid warm sessions.

        Returns:
            List of labels that need warming up.
        """
        if not self.enabled:
            return []

        needs_warmup = []
        max_age = self._config.max_age_hours

        with self._lock:
            for label in self._config.labels:
                label_lower = label.lower()

                # Skip if warming is already in progress
                if label_lower in self._warming_in_progress:
                    continue

                sessions = self._sessions.get(label_lower, [])
                valid_sessions = [
                    s for s in sessions
                    if s.exploration_complete and not s.is_expired(max_age)
                ]

                if len(valid_sessions) < self._config.pool_size_per_label:
                    needs_warmup.append(label)

        return needs_warmup

    def get_stats(self) -> dict[str, int | dict[str, int]]:
        """Get statistics about the warm session pool.

        Returns:
            Dictionary with pool statistics.
        """
        with self._lock:
            total_sessions = sum(len(sessions) for sessions in self._sessions.values())
            valid_sessions = sum(
                len([s for s in sessions if s.exploration_complete and not s.is_expired(self._config.max_age_hours)])
                for sessions in self._sessions.values()
            )
            per_label = {
                label: len(sessions)
                for label, sessions in self._sessions.items()
            }
            warming = len(self._warming_in_progress)

        return {
            "total_sessions": total_sessions,
            "valid_sessions": valid_sessions,
            "warming_in_progress": warming,
            "configured_labels": len(self._config.labels),
            "per_label": per_label,
        }

    def __repr__(self) -> str:
        stats = self.get_stats()
        return (
            f"WarmSessionPool(enabled={self.enabled}, "
            f"valid={stats['valid_sessions']}/{stats['total_sessions']}, "
            f"labels={stats['configured_labels']})"
        )


# Global pool instance (lazily initialized)
_global_pool: WarmSessionPool | None = None
_pool_lock = threading.Lock()


def get_warm_session_pool() -> WarmSessionPool:
    """Get the global warm session pool (creates if needed).

    Returns:
        The global WarmSessionPool instance.
    """
    global _global_pool

    with _pool_lock:
        if _global_pool is None:
            from pokepoke.config import get_config
            config = get_config()
            _global_pool = WarmSessionPool(config.warm_sessions)

    return _global_pool


def reset_warm_session_pool() -> None:
    """Reset the global pool (useful for testing)."""
    global _global_pool
    with _pool_lock:
        _global_pool = None
