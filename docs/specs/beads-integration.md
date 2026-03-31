---
description: Beads issue tracker integration providing task querying, status updates, and sync-strategy selection for bd and br CLI backends.
references:
  - src/pokepoke/beads/beads.py
  - src/pokepoke/beads/beads_query.py
  - src/pokepoke/beads/sdk_beads_tracker.py
  - src/pokepoke/beads/sync_strategy.py
confidence: medium
lastUpdated: 2026-03-31
---

# Spec: Beads Integration

## Purpose
- Interface with beads issue tracker for autonomous task selection and status management.
- Support both `bd` (Python) and `br` (Rust) CLI backends with automatic sync-strategy selection.
- In scope: querying ready items, updating item status, backend abstraction.
- Out of scope: beads CLI implementation, manual item creation UI.

## Component Interaction
- `beads.py`: High-level beads operations (get ready items, update status, claim item).
- `beads_query.py`: Low-level CLI command execution and JSON parsing for `bd ready --json`.
- `sync_strategy.py`: Selects appropriate backend (bd/br) based on availability and performance.
- `sdk_beads_tracker.py`: Tracks beads item lifecycle through orchestration phases.

## Design Decisions
- Beads backend is pluggable; orchestrator doesn't know which CLI is used.
- Query results return `None` on error (distinct from empty list) for error handling.
- Status updates are idempotent; duplicate updates are no-ops.
- Priority-based selection prefers higher priority items when multiple are ready.
