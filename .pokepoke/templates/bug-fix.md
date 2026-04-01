# Bug Fix Template

## Title Pattern
`Fix [component]: [brief description of bug]`

**Examples:**
- `Fix orchestrator: handle None return from get_ready_work_items`
- `Fix validation: prevent infinite retry loop on transient errors`
- `Fix beads sync: race condition in daemon status check`

## Issue Type
`bug`

## Priority Guidelines
- **P0 (Critical)**: Production broken, data loss, security vulnerability
- **P1 (High)**: Major functionality broken, affects multiple users
- **P2 (Medium)**: Minor functionality broken, workaround exists
- **P3 (Low)**: Cosmetic issue, edge case, minimal impact

## Expected Files to Modify

### Primary Implementation
- `src/pokepoke/[component]/[affected_module].py` - Fix the bug

### Testing
- `tests/[component]/test_[affected_module].py` - Add regression test
- `tests/integration/test_[workflow].py` - Add integration test if cross-component

### Documentation (if API/behavior changes)
- `README.md` - Update if user-facing behavior changes
- `docs/feature_specs/[feature].md` - Update feature spec if applicable

## Testing Approach

### Required Tests
1. **Regression Test**: Reproduce the bug, verify fix prevents recurrence
2. **Edge Cases**: Test boundary conditions that triggered the bug
3. **Integration Test**: Verify fix doesn't break related functionality

### Test Coverage Target
- **Modified files**: 80%+ line coverage (enforced by pre-commit hook)
- **New code**: 100% coverage of bug fix logic

### Example Test Structure
```python
def test_bug_fix_handles_none_return():
    """Regression test for issue bd-XXX: handle None from get_ready_work_items."""
    # Arrange: Setup condition that triggers bug
    mock_beads = Mock(return_value=None)
    
    # Act: Execute the previously-failing code path
    result = orchestrator.process_queue(mock_beads)
    
    # Assert: Verify bug is fixed (no crash, correct behavior)
    assert result is not None
    assert result.status == "no_work_available"
```

## Acceptance Criteria

### Code Changes
- [ ] Bug is fixed in the identified component
- [ ] Fix is minimal and surgical (no unrelated changes)
- [ ] No new bugs introduced (validated by existing tests)
- [ ] Error messages are clear and actionable

### Testing
- [ ] Regression test added that fails on buggy code, passes on fixed code
- [ ] All existing tests pass (no regressions)
- [ ] 80%+ coverage on modified files
- [ ] Integration tests pass if cross-component

### Documentation
- [ ] Code comments explain why bug occurred (if non-obvious)
- [ ] Commit message references issue ID (e.g., `Fix bd-XXX: ...`)
- [ ] README updated if user-facing behavior changed

### Quality Gates
- [ ] Pre-commit hooks pass (tests, coverage, linting, type checking)
- [ ] No new linting or type checking warnings
- [ ] Git status clean (all changes committed)

## Complexity Guidelines

### Low Complexity (30-60 minutes)
- One-line fix in single file
- Bug in error handling, validation, or edge case
- Clear root cause, obvious solution
- Example: Null check missing, off-by-one error

### Medium Complexity (1-3 hours)
- Fix spans 2-3 files
- Requires refactoring to resolve cleanly
- Bug in core logic with multiple edge cases
- Example: Race condition, state management bug

### High Complexity (4+ hours)
- Fix spans multiple components
- Requires architectural changes
- Bug in complex algorithm or distributed system
- Unclear root cause requiring investigation
- Example: Deadlock, memory leak, data corruption

## Labels to Add
```bash
bd label add <issue-id> <component> bug-fix --json
```

**Common component labels:**
- `orchestrator` - Orchestration loop and workflow
- `validation` - Quality gates and validation
- `beads` - Beads integration
- `worktrees` - Git worktree management
- `agents` - AI agent integration
- `config` - Configuration management

## Example Issue Creation
```bash
bd create "Fix orchestrator: handle None return from get_ready_work_items" \
  -t bug \
  -p 1 \
  -d "The orchestrator crashes with AttributeError when get_ready_work_items returns None (empty queue). Should handle gracefully and return 'no_work_available' status." \
  --json

bd label add <issue-id> orchestrator bug-fix --json
```

## Anti-Patterns to Avoid
- ❌ Fixing unrelated bugs in same commit
- ❌ Refactoring code beyond what's needed for the fix
- ❌ Adding features while fixing bugs
- ❌ Lowering test coverage thresholds
- ❌ Skipping regression tests ("it's obvious it works")
- ❌ Using `--no-verify` to bypass quality gates
