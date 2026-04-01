{{>beads-item}}

## 📋 Orchestrator Context

This work item is related to the **PokePoke orchestrator** - the core workflow management system.

### Key Files

- `src/pokepoke/orchestrator.py` - Main orchestration loop
- `src/pokepoke/orchestration/` - Orchestration components
- `src/pokepoke/models/copilot_sdk.py` - AI backend integration
- `src/pokepoke/config.py` - Configuration system

### Common Patterns

**Beads Integration:**
- Always use the configured beads backend (`bd` or `br`)
- Query ready items with `--json` flag for structured output
- Never modify beads lifecycle directly - let orchestrator own it

**Worktree Management:**
- Create worktrees with pattern: `./worktrees/task-{id}`
- Always clean up worktrees after merge or failure
- Use git isolation for concurrent task execution

**Quality Gates:**
- Pre-commit hooks enforce all validations
- Never bypass quality gates - fix the code instead
- Coverage, linting, type checks, and build must all pass

### Common Pitfalls

- ⚠️ Don't hardcode beads commands - use configured backend
- ⚠️ Don't skip worktree cleanup - leads to orphaned worktrees
- ⚠️ Don't bypass validation - breaks the autonomous workflow
- ⚠️ Test orchestration changes with both `bd` and `br` backends
