---
description: Git worktree isolation system for parallel task execution with automatic creation, cleanup, and merge handling.
references:
  - src/pokepoke/worktrees/coordination.py
  - src/pokepoke/worktrees/worktree_cleanup.py
  - src/pokepoke/worktrees/worktree_finalization.py
  - src/pokepoke/worktrees/worktree_merge_handler.py
  - src/pokepoke/worktrees/worktrees.py
confidence: medium
lastUpdated: 2026-03-31
---

# Spec: Worktree Management

## Purpose
- Isolate task execution in separate git worktrees to prevent conflicts between parallel tasks.
- Automate worktree lifecycle from creation through merge and cleanup.
- In scope: worktree creation, isolation, merge handling, cleanup.
- Out of scope: git operations implementation, conflict resolution strategies.

## Component Interaction
- `worktrees.py`: Core worktree operations (create, list, remove) with pattern `./worktrees/task-{id}`.
- `coordination.py`: Coordinates multiple worktrees, prevents duplicate creation for same task.
- `worktree_merge_handler.py`: Handles merging completed work back to main branch.
- `worktree_finalization.py`: Finalizes worktree state after successful merge.
- `worktree_cleanup.py`: Removes worktrees after completion or on failure.

## Design Decisions
- Worktree path pattern: `./worktrees/task-{beads_item_id}` for predictable location.
- Each task gets exactly one worktree; duplicate requests reuse existing.
- Merge requires all validation gates to pass; failed tasks keep worktree for debugging.
- Cleanup is aggressive after successful merge; failed worktrees preserved for investigation.
- Lock contention handled via `lock_contention.py` to prevent race conditions.
