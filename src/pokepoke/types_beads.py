"""Beads domain type definitions extracted from types.py.

Contains the core beads work-item dataclasses (BeadsWorkItem, BeadsCreatedItem,
Dependency, IssueWithDependencies) and the RecordFn callback protocol used by
the parallel orchestration layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pokepoke.types import WorkItemResult
    from pokepoke.types_stats import SessionStats
    from pokepoke.utils.logging_utils import RunLogger


@dataclass
class BeadsWorkItem:
    """Represents a beads work item from bd ready --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: str | None = None
    owner: str | None = None
    assignee: str | None = None  # Agent actively working on it (pokepoke_agent_123)
    created_at: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None  # Metadata from beads (gate_rejection_count, etc.)
    is_ephemeral: bool = False  # True for synthetic items (cleanup, maintenance) not in beads DB

    def __post_init__(self) -> None:
        # bd v1.0.3+ may return metadata as a JSON string; normalise to dict.
        if isinstance(self.metadata, str):
            import json
            try:
                self.metadata = json.loads(self.metadata)
            except (json.JSONDecodeError, TypeError):
                self.metadata = None

@dataclass(frozen=True)
class BeadsCreatedItem:
    """A beads item created by an agent during the session."""
    id: str
    title: str = ""
    agent_type: str = "unknown"

@dataclass
class Dependency:
    """Represents a dependency relationship."""
    id: str
    title: str
    issue_type: str
    dependency_type: str  # parent, blocks, related, discovered-from
    status: str | None = None
    priority: int | None = None
    description: str | None = None
    owner: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    labels: list[str] | None = None
    notes: str | None = None

@dataclass
class IssueWithDependencies:
    """Represents an issue with full dependency information from bd show --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: str | None = None
    dependencies: list[Dependency] | None = None
    dependents: list[Dependency] | None = None
    owner: str | None = None
    assignee: str | None = None  # Agent actively working on it (pokepoke_agent_123)
    created_at: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    labels: list[str] | None = None
    notes: str | None = None


class RecordFn(Protocol):
    """Protocol for work item result recording callbacks.

    Used in parallel worker finalization to record completed work item results.
    The return value is ignored by callers.
    """
    def __call__(
        self,
        item: BeadsWorkItem,
        result: WorkItemResult,
        session_stats: SessionStats,
        run_logger: RunLogger,
    ) -> Any:
        """Record the result of processing a work item.

        Parameters
        ----------
        item : BeadsWorkItem
            The work item that was processed.
        result : WorkItemResult
            The result of processing the work item.
        session_stats : SessionStats
            Session statistics to update.
        run_logger : RunLogger
            Logger for orchestrator messages.

        Returns
        -------
        Any
            Return value is ignored by callers (may return None or tuple).
        """
        ...
