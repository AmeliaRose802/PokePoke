"""Agent result types for PokePoke orchestrator.

Contains result dataclasses returned by the work agent (CopilotResult)
and gate agent (GateAgentResult).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pokepoke.work_agent_outcome import WorkAgentOutcome

if TYPE_CHECKING:
    from pokepoke.types_stats import AgentStats


@dataclass
class CopilotResult:
    """Result from invoking Copilot CLI."""
    work_item_id: str
    success: bool
    output: str | None = None
    error: str | None = None
    validation_errors: list[str] | None = None
    attempt_count: int = 1
    is_rate_limited: bool = False  # True if error was due to rate limiting
    stats: AgentStats | None = None
    model: str | None = None  # Model used for this invocation
    session_id: str | None = None  # SDK session ID, reusable for resume on timeout
    last_output_summary: str | None = None  # Truncated output summary for retry context
    work_agent_outcome: WorkAgentOutcome | None = None  # Structured outcome from work agent

@dataclass
class GateAgentResult:
    """Result from running the gate agent."""
    success: bool
    reason: str
    stats: AgentStats | None = None
    crashed: bool = False
    is_timeout: bool = False
    session_id: str | None = None
    last_output_summary: str | None = None
    def __iter__(self) -> Iterator[Any]:
        return iter((self.success, self.reason, self.stats, self.crashed))
    def __len__(self) -> int:
        return 4
