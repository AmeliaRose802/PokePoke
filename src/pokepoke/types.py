"""Type definitions for PokePoke orchestrator."""

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class BeadsWorkItem:
    """Represents a beads work item from bd ready --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: Optional[str] = None
    owner: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None
    dependency_count: Optional[int] = None
    dependent_count: Optional[int] = None
    notes: Optional[str] = None


@dataclass
class Dependency:
    """Represents a dependency relationship."""
    id: str
    title: str
    issue_type: str
    dependency_type: str  # parent, blocks, related, discovered-from
    status: Optional[str] = None
    priority: Optional[int] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None
    notes: Optional[str] = None


@dataclass
class IssueWithDependencies:
    """Represents an issue with full dependency information from bd show --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: Optional[str] = None
    dependencies: Optional[List[Dependency]] = None
    dependents: Optional[List[Dependency]] = None
    owner: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None
    notes: Optional[str] = None


@dataclass
class RetryConfig:
    """Configuration for retry logic with exponential backoff."""
    max_retries: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    backoff_factor: float = 2.0
    jitter: bool = True  # Add random jitter to prevent thundering herd


@dataclass
class AgentStats:
    """Statistics from agent execution."""
    wall_duration: float = 0.0  # seconds
    api_duration: float = 0.0  # seconds
    input_tokens: int = 0
    output_tokens: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    premium_requests: int = 0


@dataclass
class BeadsStats:
    """Statistics from beads database."""
    total_issues: int = 0
    open_issues: int = 0
    in_progress_issues: int = 0
    closed_issues: int = 0
    ready_issues: int = 0


@dataclass
class SessionStats:
    """Combined session statistics including agent stats and run counts."""
    agent_stats: AgentStats
    work_agent_runs: int = 0
    tech_debt_agent_runs: int = 0
    janitor_agent_runs: int = 0
    backlog_cleanup_agent_runs: int = 0
    cleanup_agent_runs: int = 0
    starting_beads_stats: Optional[BeadsStats] = None
    ending_beads_stats: Optional[BeadsStats] = None


@dataclass
class CopilotResult:
    """Result from invoking Copilot CLI."""
    work_item_id: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    validation_errors: Optional[List[str]] = None
    attempt_count: int = 1
    is_rate_limited: bool = False  # True if error was due to rate limiting
    stats: Optional[AgentStats] = None
