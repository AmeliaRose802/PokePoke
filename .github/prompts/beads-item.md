Your job is to address a specific beads item in your worktree, then merge and close the item.

You are working on item: {{item_id}}

Description: {{}}

**Your Responsibilities:**

1. **Complete the work** - Fully implement the requested changes
2. **Commit changes** - All pre-commit validation must pass
3. **Merge your worktree** - Use `git push` to push commits, then return to main repo and merge
4. **Close the beads item** - Run `bd close {{item_id}} --reason "<completion reason>"`

**Success Criteria:**

- Provided item is fully implemented
- All pre-commit validation passes successfully  
- Worktree merged back to main branch
- Beads item closed with appropriate reason

**Important Notes:**
- Work is NOT complete until worktree is merged
- Use `bd show {{item_id}}` to get additional context on the item
- The orchestrator will verify closure and handle it if you miss this step