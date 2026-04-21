---
description: Main autonomous workflow loop coordinating work item selection, agent execution, validation, and retry with corrective feedback.
references:
  - src/pokepoke/orchestration/orchestrator.py
  - src/pokepoke/orchestration/workflow.py
  - src/pokepoke/orchestration/work_item_selection.py
  - src/pokepoke/orchestration/work_item_session.py
confidence: medium
lastUpdated: 2026-04-21
---

# Spec: Orchestration Workflow

## Purpose
- Implement autonomous development workflow that processes beads items without human intervention.
- Coordinate work item selection, worktree creation, agent execution, validation, and retry loops.
- In scope: workflow state machine, retry logic, work item lifecycle.
- Out of scope: agent implementations, git operations, validation rules.

## Component Interaction
- `orchestrator.py`: Main entry point; CLI interface for interactive/autonomous/continuous modes.
- `workflow.py`: Core workflow state machine managing task lifecycle from selection to completion.
- `work_item_selection.py`: Queries beads for ready items, filters and ranks by priority.
- `work_item_session.py`: Manages per-item execution session with isolated state.


## Design Decisions
- Infinite retry loop with intelligent corrective prompts until validation passes.
- Work items processed in priority order; ties broken by creation date.
- Each work item executes in isolated worktree to prevent conflicts.
- Validation failures accumulate context for progressively better retry prompts.
- Continuous mode loops after completion; single-shot mode exits after one item.
- Work-agent `needs_clarification` outcomes are treated as human-required blockers:
  the workflow marks the item `blocked` with clarification details and avoids
  returning it to the ready queue.
