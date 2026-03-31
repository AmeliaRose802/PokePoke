---
description: Agent discovery and registration system enabling dynamic loading and type-safe spawning of task, cleanup, and decomposition agents.
references:
  - src/pokepoke/agents/agent_context.py
  - src/pokepoke/agents/agent_registry.py
  - src/pokepoke/agents/agent_runner.py
  - src/pokepoke/agents/agent_types.py
confidence: medium
lastUpdated: 2026-03-31
---

# Spec: Agent Registry

## Purpose
- Enable dynamic agent discovery and registration without hardcoding agent types.
- Support type-safe agent spawning with context injection.
- In scope: agent registration, discovery, spawning, context management.
- Out of scope: specific agent implementations, parallel execution runtime.

## Component Interaction
- `agent_registry.py`: Central registry mapping agent names to implementations; entry point for agent discovery.
- `agent_types.py`: Type definitions and enums for agent categories (task, cleanup, decomposition, gate).
- `agent_runner.py`: Executes registered agents with proper context and timeout handling.
- `agent_context.py`: Provides execution context (worktree path, config, beads item) to running agents.

## Design Decisions
- Registry pattern allows adding new agent types without modifying orchestration code.
- Agents receive context via dependency injection rather than global state.
- Agent names use snake_case identifiers for CLI compatibility.
