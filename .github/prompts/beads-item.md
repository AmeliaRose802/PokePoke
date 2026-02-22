Your job is to address a specific beads item in your worktree, then merge and close the item.

You are working on item: {{item_id}}

## ⚠️ CRITICAL: Avoiding Hung Commands

**Command Timeout: {{command_timeout}} seconds**

Long-running commands can hang indefinitely, wasting time. Follow these rules:

1. **Always use timeouts for pytest:**
   ```powershell
   pytest --timeout={{command_timeout}}
   ```
   NEVER run bare `pytest` without --timeout flag.

2. **For targeted test runs, still use --timeout:**
   ```powershell
   pytest tests/test_specific_module.py --timeout={{command_timeout}}
   ```
   Running specific test files is faster and less likely to hang.

3. **If a test run times out, retry with -x --timeout=15:**
   ```powershell
   pytest -x --timeout=15
   ```
   This helps identify the specific hanging test by stopping on first failure with a shorter timeout.

4. **If a command appears stuck:**
   - After 2-3 `read_powershell` calls with no new output, the command is likely hung
   - Use `stop_powershell` to kill the hung process
   - Retry with a timeout flag or run targeted tests instead

5. **For builds/installs:**
   Use reasonable initial_wait values and be prepared to stop if hung.

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