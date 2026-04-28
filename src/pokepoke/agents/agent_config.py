"""Configuration dataclasses for agent invocation parameters.

This module provides typed configuration objects that bundle multiple
parameters together, reducing function signature complexity and improving
maintainability.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger


@dataclass
class AgentStatusConfig:
    """Configuration for agent status updates in the registry.

    Bundles the many optional parameters for AgentRegistry.update_status()
    to avoid PLR0913 (too many parameters) violations.
    """
    agent_id: str
    name: str
    iteration: int
    status: str
    model: str | None = None
    parent_agent_id: str | None = None
    work_item_id: str | None = None
    work_item_title: str | None = None
    agent_prompt: str | None = None
    session_id: str | None = None
    modified_files: list[str] | None = None
    agent_type: str | None = None
    resume_in_place: bool = False


@dataclass
class CleanupAgentConfig:
    """Configuration for cleanup agent invocation.

    Bundles parameters for _run_agent_with_ui to reduce function signature
    complexity.
    """
    agent_id: str
    agent_label: str
    agent_type_key: str
    cwd: str | None
    parent_agent_id: str | None
    work_item_id: str | None = None
    work_item_title: str | None = None
    modified_files: list[str] | None = None
    timeout: float | None = None
    item_logger: ItemLogger | None = None


@dataclass
class CleanupInvocationConfig:
    """Configuration for invoking cleanup or merge-conflict cleanup agents.

    Bundles shared optional parameters for invoke_cleanup_agent() and
    invoke_merge_conflict_cleanup_agent().
    """
    cwd: str | None = None
    parent_agent_id: str | None = None
    wait_for_merge: bool = True
    item_logger: ItemLogger | None = None


@dataclass
class GateAgentConfig:
    """Configuration for gate agent execution.

    Bundles the many optional parameters for run_gate_agent() to avoid
    PLR0913 violations while maintaining backward compatibility.
    """
    cwd: str | None = None
    work_model: str | None = None
    handoff_context: str | None = None
    previous_output_summary: str | None = None
    agent_id: str | None = None
    agent_iteration: int = 1
    parent_agent_id: str | None = None
    item_logger: ItemLogger | None = None
    session_id: str | None = None
    is_resume: bool = False
    resume_reason: str | None = None
    resume_feedback: str | None = None


@dataclass
class MaintenanceRunConfig:
    """Configuration for a single run_maintenance_agent() invocation.

    Bundles optional parameters for run_maintenance_agent() to reduce
    function signature complexity.
    """
    repo_root: Path | None = None
    needs_worktree: bool = True
    needs_shell: bool = False
    merge_changes: bool = True
    model: str | None = None
    item_logger: ItemLogger | None = None
    parent_agent_id: str | None = None
