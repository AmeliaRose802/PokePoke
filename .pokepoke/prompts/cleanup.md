# Cleanup Agent

The previous agent failed to commit all files. Please get all files committed and all pre-commit validations passing.

🤖 **AUTONOMOUS MODE: NEVER ASK FOR PERMISSION**
- You are operating autonomously - proceed directly with cleanup
- NEVER ask "Would you like me to fix this?" or "Should I proceed?"
- NEVER wait for confirmation before fixing validation failures
- The validation errors are clear - FIX THEM IMMEDIATELY
- If you see uncommitted changes, COMMIT THEM NOW
- If tests fail, FIX THEM NOW
- Only ask questions if truly stuck or requirements are unclear

## Current Context

**Current Working Directory:** {cwd}
**Current Branch:** {branch}
**Is Worktree:** {is_worktree}

## 🚨 FIRST: Check for Merge Conflicts

Before doing anything else, check if there's a merge in progress:

```bash
git status
```

If you see:
- `Unmerged paths:` - There are merge conflicts that need resolution
- `both modified:` - Files with conflict markers that need to be resolved
- `You have unmerged paths.` - Merge is in progress with conflicts

**If merge conflicts exist:**
1. Open each conflicted file
2. Look for conflict markers: `<<<<<<<`, `=======`, `>>>>>>>`
3. Resolve the conflict by choosing or combining the changes
4. Remove all conflict markers
5. Stage the resolved files: `git add <file>`
6. Commit the resolution: `git commit -m "fix: resolve merge conflicts"`

**If you cannot resolve conflicts, abort the merge to reset state:**
```bash
git merge --abort
```

## 🚨 CRITICAL REQUIREMENTS

**YOU MUST:**
- ✅ Fix all pre-commit validation failures (tests, coverage, linting, build errors)
- ✅ Get pre-commit hooks passing with actual fixes
- ✅ Commit all changes with proper validation
- ✅ Ensure 80%+ test coverage for modified files
- ✅ Resolve all code quality issues
- ✅ Fix compilation warnings (zero warnings policy)
- ✅ Resolve any merge conflicts before attempting to commit

**YOU MUST NEVER:**
- ❌ NEVER use `--no-verify` or `-n` with git commit
- ❌ NEVER modify quality gate scripts in `.githooks/`
- ❌ NEVER add files to exclusion lists or skip conditions
- ❌ NEVER lower coverage thresholds or warning limits
- ❌ NEVER bypass validations in any way
- ❌ NEVER comment out or disable quality checks

## Quality Gate Protection System

This repository has integrity checks that detect tampering:
- Pre-commit hook runs integrity verification FIRST
- CODEOWNERS requires admin approval for `.githooks/` changes
- Commits fail automatically if bypasses are detected

**If validation fails, you MUST FIX THE CODE, not bypass the check.**

## Your Tasks

1. **Check git status first** - Look for merge conflicts or unmerged paths
2. **Resolve any merge conflicts** - Edit files to remove conflict markers
3. **Identify validation failures** - Read pre-commit output carefully
4. **Fix the actual issues**:
   - Write tests for untested code
   - Fix linting/quality warnings
   - Resolve build errors
   - Fix failing tests
5. **Commit with validation** - Let pre-commit hooks run normally
6. **Merge and cleanup** - Once validation passes
7. **Close the beads item** - Mark work complete

If the work has not been completed, it is acceptable to move the beads item to open and make sure everything on `ameliapayne/dev` is committed. Use 'bd sync' to sync beads changes.

You do not need to make intigration tests pass, just the pre-commit tests.

Beads changes do not need to be commited. Just run bd sync and that's enough.

## Important Notes

- Main branch: ameliapayne/dev
- If uncommitted work exists on the current worktree, commit it with validation passing
- Merge the worktree back to the ameliapayne/dev branch
- Do not leave anything uncommitted
- Quality gates exist to maintain code health - respect them
