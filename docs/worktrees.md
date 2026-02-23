# Git Worktree Integration

## Overview

PokePoke uses automatic git worktree creation for isolated task execution. Each beads work item is processed in its own isolated worktree, preventing conflicts and allowing parallel work.

## Features

- **Automatic worktree creation** when processing a work item
- **Isolated execution** - each task gets its own branch and working directory
- **Automatic cleanup** after task completion
- **Safe cleanup** with uncommitted change detection

## Worktree Structure

Worktrees are created in the `./worktrees` directory at the repository root:

```
PokePoke/
├── .git/
├── worktrees/
│   ├── task-incredible_icm-123/    # Worktree for issue 123
│   ├── task-incredible_icm-456/    # Worktree for issue 456
│   └── ...
├── src/
└── ...
```

Each worktree creates a new branch: `task/<work-item-id>`

## How It Works

1. **Work Item Retrieved**: When a work item is selected from beads
2. **Worktree Created**: A new worktree is created in `./worktrees/task-{id}`
3. **Branch Created**: A new branch `task/{id}` is created from the source branch
4. **Execution**: The configured AI backend runs in the worktree directory
5. **Cleanup**: After completion, the worktree is removed

## Benefits

- **Isolation**: Each task works in its own directory
- **Parallel Execution**: Multiple agents can work simultaneously
- **No Conflicts**: Changes don't interfere with the main working tree
- **Clean Branches**: Each task gets its own branch
- **Safety**: Source branch remains untouched

## Cleanup Behavior

### Normal Cleanup (force=False)
- Removes worktree if no uncommitted changes
- Fails if there are uncommitted changes (safety check)
- Attempts to delete the task branch (only if merged)

### Force Cleanup (force=True)
- Removes worktree even with uncommitted changes
- Use with caution - uncommitted work will be lost

## Integration with Orchestrator

The orchestrator automatically uses worktrees when available. AI backends are selected via `.pokepoke/config.yaml` (`ai_backend.provider`), defaulting to Copilot with a Claude Code adapter available when `provider: claude-code` is set.

## Agent Naming for Parallel Instances

When running multiple PokePoke instances in parallel, each instance automatically generates a unique agent name with good entropy to prevent conflicts when assigning work items.

### Automatic Agent Name Generation

Each PokePoke run generates a unique name in the format:
```
pokepoke_{adjective}_{creature}_{hex}
```

Examples:
- `pokepoke_swift_pika_a7f3`
- `pokepoke_cunning_gengar_c41a`
- `pokepoke_mighty_charizard_d994`

The naming scheme provides:
- **~87 million unique combinations** (35+ adjectives × 38+ creatures × 65,536 hex values)
- **26 bits of entropy** for collision-free parallel execution
- **Memorable names** that are easy to identify in logs and beads assignments

### How It Works

1. **Startup**: Each PokePoke instance generates a random agent name on startup
2. **Environment Variable**: The name is stored in `$AGENT_NAME` environment variable
3. **Work Assignment**: When claiming work items, the agent name is used: `bd update <id> --assign <agent_name>`
4. **Conflict Prevention**: Other agents see the assignment and avoid claiming the same item

### Manual Agent Names

If you want to pin a specific name for a run, pass it directly to the orchestrator:

```powershell
python -m pokepoke.orchestrator --interactive --agent-name Janitor
```

Otherwise, PokePoke will automatically generate a unique name for you.

## Troubleshooting

### Branch already exists
The cleanup method attempts to delete branches, but only if they're merged. Unmerged branches are left intact (by design).
