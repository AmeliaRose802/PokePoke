"""Type definitions for PokePoke orchestrator."""

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class BeadsWorkItem:
    """Represents a beads work item from bd ready --json."""
    id: str
    title: str
    description: str
    status: str
    priority: int
    issue_type: str
    owner: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None
    dependency_count: Optional[int] = None
    dependent_count: Optional[int] = None


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


@dataclass
class IssueWithDependencies:
    """Represents an issue with full dependency information from bd show --json."""
    id: str
    title: str
    description: str
    status: str
    priority: int
    issue_type: str
    dependencies: Optional[List[Dependency]] = None
    dependents: Optional[List[Dependency]] = None
    owner: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None


@dataclass
class CopilotResult:
    """Result from invoking Copilot CLI."""
    work_item_id: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    validation_errors: Optional[List[str]] = None
    attempt_count: int = 1
