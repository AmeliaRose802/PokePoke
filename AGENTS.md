# Agent Instructions

This project uses **beads** for issue tracking with a pluggable CLI backend.
The default backend is `bd` (Python). An alternative Rust backend `br` is also supported.
Run `bd onboard` (or `br onboard`) to get started.

## Quick Reference

```bash
# Default backend (bd)
bd ready                    # Find available work
bd show <id>                # View issue details
bd list --deps <id>         # Check dependencies
bd list --label <label>     # Find related items by label
bd sync                     # Sync with git
```

> **Note:** Agents should not run `bd update`/`bd close` for orchestrated work items.
> The orchestrator owns lifecycle transitions (claim/close/unassign).

> **Note:** All `bd` commands work identically with `br`. PokePoke selects the
> active backend automatically based on configuration (see README.md).

## Beads + Worktree Coordination

- Claiming a beads item and creating its worktree is now serialized through `.pokepoke/locks/worktree-setup.lock`.
- All `assign_and_sync_item()` and `git worktree add` calls inside the orchestrator run under this lock so only one agent mutates `.beads/` + `.git/worktrees/` at a time.
- Never bypass this lock (e.g., by calling `assign_and_sync_item()` directly) or you risk double-claiming issues and corrupting the repo.
- If you are building new tooling that also claims beads items, reuse the same lock to keep the critical section atomic.
- The lock coordination works the same regardless of which beads backend (`bd` or `br`) is active.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

