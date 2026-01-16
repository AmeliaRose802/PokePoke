# Git Worktree Integration

## Overview

PokePoke now supports automatic git worktree creation for isolated task execution. When enabled, each beads work item is processed in its own isolated worktree, preventing conflicts and allowing parallel work.

## Features

- **Automatic worktree creation** when processing a work item
- **Isolated execution** - each task gets its own branch and working directory
- **Automatic cleanup** after task completion
- **Configurable source branch** (defaults to `master`)
- **Safe cleanup** with uncommitted change detection

## Usage

### Basic Usage (Worktrees Enabled by Default)

```python
from pokepoke import CopilotInvoker, BeadsWorkItem

# Worktrees are enabled by default
invoker = CopilotInvoker(
    model="claude-sonnet-4.5",
    use_worktrees=True,  # This is the default
    source_branch="master"  # Branch to create worktrees from
)

# Process a work item - worktree is automatically created and cleaned up
result = invoker.invoke(work_item)
```

### Disable Worktrees

```python
# Disable worktrees to work in the current directory
invoker = CopilotInvoker(
    use_worktrees=False
)

result = invoker.invoke(work_item)
```

### Direct WorktreeManager Usage

```python
from pokepoke import WorktreeManager

manager = WorktreeManager()  # Uses ./worktrees by default

# Create worktree
success, message, path = manager.create_worktree(
    work_item_id="incredible_icm-123",
    source_branch="master"
)

if success:
    print(f"Worktree created at: {path}")
    
    # Do work in the worktree...
    
    # Clean up when done
    success, message = manager.cleanup_worktree(
        work_item_id="incredible_icm-123",
        force=False  # Set to True to force removal
    )
```

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
4. **Execution**: Copilot CLI runs in the worktree directory
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

The orchestrator automatically uses worktrees when available. The backward-compatible `invoke_copilot_cli` function enables worktrees by default.

## Listing Worktrees

```python
from pokepoke import WorktreeManager

manager = WorktreeManager()
worktrees = manager.list_worktrees()

for wt in worktrees:
    print(f"Path: {wt['path']}")
    print(f"Branch: {wt.get('branch', 'no branch')}")
    print(f"HEAD: {wt.get('head', 'unknown')}")
```

## Error Handling

The worktree manager returns tuples for status:

```python
success, message, path = manager.create_worktree(work_item_id, source_branch)
if not success:
    print(f"Error: {message}")
else:
    print(f"Success: {message}")
    print(f"Path: {path}")
```

## Best Practices

1. **Always clean up**: Worktrees are automatically cleaned up in a finally block
2. **Check for conflicts**: Ensure no duplicate worktree names
3. **Use meaningful IDs**: Work item IDs become part of paths and branch names
4. **Source branch**: Ensure source branch is up to date before creating worktrees
5. **Parallel work**: Each agent should have unique work item IDs

## Troubleshooting

### Worktree already exists
```python
# Clean up existing worktree first
manager.cleanup_worktree(work_item_id, force=True)

# Then create new one
manager.create_worktree(work_item_id, source_branch)
```

### Cleanup fails with uncommitted changes
```python
# Option 1: Commit the changes first (recommended)
# Option 2: Force cleanup (loses changes)
manager.cleanup_worktree(work_item_id, force=True)
```

### Branch already exists
The cleanup method attempts to delete branches, but only if they're merged. Unmerged branches are left intact (by design).
