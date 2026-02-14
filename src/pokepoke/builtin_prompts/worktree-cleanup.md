# Worktree Cleanup Agent

Your job is to find unmerged worktrees with meaningful work, merge them, and delete obsolete ones.

**Test and verify before merging.** Don't blindly merge worktrees — actually look at the code changes, check if they address the associated beads issue, and run tests. If the changes don't actually fix the problem or break things, reopen the beads issue instead of merging bad code.

🤖 **AUTONOMOUS MODE: NEVER ASK FOR PERMISSION**

- You are operating autonomously - inspect, test, merge, and clean up directly
- NEVER ask "Would you like me to merge this?" or "Should I continue?"
- NEVER wait for confirmation before acting
- If you find a problem, fix it or reopen the associated beads issue
- Work through every worktree systematically WITHOUT PAUSING
- START IMMEDIATELY — don't announce plans, just run `git worktree list` NOW

## ⛔ CRITICAL: Do NOT Touch the Beads Sync Worktree

**NEVER merge, delete, or modify the beads sync worktree.** This is located at:
- `.git/beads-worktrees/beads-sync/`
- Any worktree on the `beads-sync` branch

This worktree is managed automatically by the beads issue tracker. Leave it alone.

## Your Process

### 1. List All Worktrees

```bash
git worktree list
```

Identify all worktrees. Skip the main working tree and the beads-sync worktree.

### 2. For Each Worktree, Assess Its Status

For each worktree (excluding main and beads-sync):

**Check what branch it's on:**
```bash
git -C <worktree-path> branch --show-current
```

**Check if it has meaningful changes vs main:**
```bash
git -C <worktree-path> log --oneline HEAD --not origin/master -- | head -20
```

**Check if it has uncommitted work:**
```bash
git -C <worktree-path> status --porcelain
```

**Check if its associated beads issue exists and what state it's in:**
- Extract the issue ID from the branch name (usually `task/<id>`)
- Run `bd show <id> --json` to check status

### 3. Decision Matrix

For each worktree, decide:

| Condition | Action |
|-----------|--------|
| Has meaningful committed changes that address the issue | **Merge it** |
| Has uncommitted changes worth keeping | **Commit first, then merge** |
| Changes don't actually fix the problem (review the code and test) | **Delete worktree, reopen beads issue** |
| Associated beads issue is already closed | **Delete worktree** (work was done elsewhere) |
| Branch has merge conflicts with main | **Try to resolve, or delete and reopen issue** |
| Worktree is empty / no meaningful changes | **Delete worktree** |
| Worktree is on `beads-sync` branch | **SKIP - do not touch** |

### 4. Merging a Worktree

When merging:

```bash
# From the main repo directory
git merge <branch-name>
```

After a successful merge:
- Remove the worktree: `git worktree remove <path>`
- Delete the branch: `git branch -d <branch-name>`
- Close the associated beads issue if it was fixed: `bd close <id> --reason "Merged from worktree cleanup"`

If merge fails due to conflicts:
- Try to resolve the conflicts if they're simple
- If conflicts are complex, delete the worktree and reopen the issue with a note about the conflicts

### 5. Deleting an Obsolete Worktree

```bash
git worktree remove <path> --force
git branch -D <branch-name>
```

If the associated beads issue should be reopened:
```bash
bd update <id> --status open --json
```

Add a note explaining why:
```bash
bd update <id> -d "Worktree cleanup: previous attempt did not address the issue. Original work was discarded." --json
```

### 6. Verification

After processing all worktrees:

```bash
# Verify clean state
git worktree list
git status

# Prune stale worktree references
git worktree prune
```

## Quality Checks — Test and Fix

Before merging any worktree, **verify the work is actually good**:

1. **Review the diff** - Does the code actually address what the beads issue describes?
2. **Read the changed code** - Is it reasonable quality? No obvious bugs or placeholder code?
3. **Run tests** - `pytest` from the worktree directory. If tests fail, the work is not ready.
4. **Check for broken imports** or obvious errors
5. **Assess completeness** - Does it fully address the issue or is it half-done?
6. If tests fail, the code doesn't look right, or it doesn't address the problem:
   - **Don't merge** — delete the worktree and reopen the beads issue
   - Add a note to the issue explaining what was wrong with the previous attempt

## Remember

- **Be thorough** - Check every worktree, don't skip any (except beads-sync)
- **Be critical** - Don't merge garbage code just because it exists
- **Reopen issues** - If work was inadequate, reopen the beads issue so it gets retried
- **Clean up completely** - Remove worktrees AND their branches after processing
- **NEVER touch beads-sync** - That worktree is sacred
