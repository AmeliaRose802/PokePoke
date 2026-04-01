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

## 🚨 CRITICAL: Test Safety Requirements

**NEVER create tests with real subprocess, git, or filesystem operations without proper mocks.**

### Mandatory Test Safety Rules

All tests MUST follow these rules to prevent hangs in worktrees and CI:

1. **USE MOCKS for subprocess calls:**
   - ✅ Use `FakeGitClient` or `FakeBeadsClient` from `tests/fakes.py`
   - ✅ Use `@patch('subprocess.run')` or `@patch('pokepoke.module._run_bd')`
   - ❌ NEVER call `subprocess.run()`, `subprocess.Popen()`, or `os.system()` directly

2. **USE MOCKS for git operations:**
   - ✅ Use `FakeGitClient` from `tests/fakes.py`
   - ✅ Use `@patch('pokepoke.git.git_helpers.run_git')`
   - ❌ NEVER execute real `git worktree`, `git add`, `git commit`, `git push` commands

3. **USE MOCKS for filesystem operations:**
   - ✅ Use `tmp_path` pytest fixture for temporary files
   - ✅ Mock `shutil.rmtree`, `os.remove`, etc.
   - ❌ NEVER manipulate real repository files

4. **ALWAYS include timeouts:**
   - All tests automatically have a 10-second timeout (pyproject.toml)
   - pytest-timeout plugin is required and enforced in conftest.py

### Exemption Markers

Only use these markers for genuine integration tests:

- `@pytest.mark.allow_real_bd` - Allow real beads CLI subprocess calls
- `@pytest.mark.allow_git_repair` - Allow real git commands

**Example:** Integration test that must run real git commands:

```python
@pytest.mark.allow_git_repair
def test_git_repair_workflow():
    """Integration test for git repair - requires real git operations."""
    # This test can run real subprocess.run(['git', ...]) calls
    pass
```

### Quality Gate Enforcement

The pre-commit hook includes `check-test-safety.ps1` which:
- Scans all staged test files
- Detects unmocked subprocess, git, and filesystem operations
- Blocks commits if unsafe patterns are found

**This gate CANNOT be bypassed** - see `.github/copilot-instructions.md` for protection system details.

### Examples: Safe vs Unsafe Tests

#### ❌ UNSAFE: Real subprocess call
```python
def test_get_git_status():
    # WRONG: Real git command, will hang in worktrees
    result = subprocess.run(['git', 'status'], capture_output=True)
    assert result.returncode == 0
```

#### ✅ SAFE: Using FakeGitClient
```python
def test_get_git_status():
    # CORRECT: Using fake client from tests/fakes.py
    fake_git = FakeGitClient()
    fake_git.run_git_results.append(_completed(stdout="nothing to commit"))
    
    result = fake_git.run_git(['status'])
    assert result.returncode == 0
```

#### ❌ UNSAFE: Real beads CLI call
```python
def test_get_ready_items():
    # WRONG: Real bd subprocess, will hang on file locks
    result = subprocess.run(['bd', 'ready', '--json'], capture_output=True)
    assert result.returncode == 0
```

#### ✅ SAFE: Using patch
```python
@patch('pokepoke.beads.beads_query._run_bd')
def test_get_ready_items(mock_run_bd):
    # CORRECT: Mocked subprocess call
    mock_run_bd.return_value = _completed(stdout='[{"id":"task-1"}]')
    
    items = get_ready_work_items()
    assert len(items) == 1
```

### Why This Matters

**Historical context:** In run 20260330_154935, agents created integration tests with real git and filesystem operations that caused repeated pytest hangs. Tests like `test_orphan_cleanup_integration.py` ran real subprocess calls without timeouts, blocking the entire test suite.

**Prevention:** These rules and the quality gate prevent similar issues from being created in the future.

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

