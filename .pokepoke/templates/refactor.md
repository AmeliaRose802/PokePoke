# Refactor Template

## Title Pattern
`Refactor [component]: [brief description of improvement]`

**Examples:**
- `Refactor orchestrator: extract retry logic into separate module`
- `Refactor beads: consolidate query operations into beads_query.py`
- `Refactor validation: replace procedural code with ValidationPipeline class`

## Issue Type
`task` (use `refactor` label)

## Priority Guidelines
- **P0 (Critical)**: Blocking other work, code is unmaintainable/dangerous
- **P1 (High)**: Significant technical debt, impacts velocity
- **P2 (Medium)**: Code quality improvement, moderate debt
- **P3 (Low)**: Nice to have, minor cleanup

## Expected Files to Modify

### Primary Refactoring
- `src/pokepoke/[component]/[module].py` - Refactor target module
- `src/pokepoke/[component]/[new_module].py` - Extract into new module (if splitting)

### Testing
- `tests/[component]/test_[module].py` - Update tests for new structure
- `tests/integration/test_[workflow].py` - Verify end-to-end behavior unchanged

### Documentation (if structure changes)
- `docs/feature_specs/[feature].md` - Update if architecture changes
- Code comments - Add/update to explain refactored design

## Testing Approach

### Critical Principle
**Behavior MUST NOT change** - Refactoring changes structure, not functionality.

### Required Tests
1. **Existing Tests Pass**: All existing tests must pass unchanged
2. **Test Refactoring**: Update tests if internal structure changed, preserve assertions
3. **Integration Tests**: Verify end-to-end workflows work identically
4. **Coverage Maintained**: Coverage must not decrease

### Test Strategy
```python
# BEFORE refactoring: Run tests, capture baseline
pytest tests/[component]/ --cov=src/pokepoke/[component] --cov-report=term

# DURING refactoring: Run tests frequently to catch breaks early
pytest tests/[component]/ -x  # Stop on first failure

# AFTER refactoring: Verify tests still pass, coverage maintained
pytest tests/[component]/ --cov=src/pokepoke/[component] --cov-report=term
# Coverage should be >= baseline
```

### When to Update Tests
- **Update imports**: If module structure changed
- **Update mocking**: If internal dependencies changed
- **Preserve assertions**: Behavior must match exactly
- **Do NOT change**: Expected values, test logic, assertions

### Example Test Update
```python
# BEFORE refactoring
from pokepoke.orchestrator import run_workflow

def test_workflow_execution():
    result = run_workflow(config)
    assert result.success

# AFTER refactoring (extracted retry logic)
from pokepoke.orchestrator import run_workflow  # Interface unchanged
# OR if interface changed:
from pokepoke.orchestrator.workflow_runner import WorkflowRunner

def test_workflow_execution():
    # Update instantiation if needed
    runner = WorkflowRunner(config)
    result = runner.run()
    
    # Assertions MUST remain identical
    assert result.success
```

## Acceptance Criteria

### Refactoring Goals
- [ ] Code is more readable and maintainable
- [ ] Duplicated code is eliminated (DRY)
- [ ] Complex functions are broken into smaller, focused functions
- [ ] Module boundaries are clearer
- [ ] Technical debt is reduced

### Behavior Preservation
- [ ] All existing tests pass without modification (or with import-only changes)
- [ ] Integration tests pass unchanged
- [ ] No user-facing behavior changed
- [ ] Performance is same or better (no regressions)

### Code Quality
- [ ] Functions have single responsibility
- [ ] No code duplication
- [ ] Clear, self-documenting names
- [ ] Complex logic has explanatory comments
- [ ] Type hints are accurate and helpful

### Testing
- [ ] Test coverage maintained or improved
- [ ] Tests updated only for structure changes, not behavior
- [ ] All pre-commit hooks pass
- [ ] 80%+ coverage on refactored files

### Documentation
- [ ] Code comments explain design decisions
- [ ] Architecture docs updated if structure changed significantly
- [ ] Public API documentation unchanged (unless internal-only refactor)

## Complexity Guidelines

### Low Complexity (1-2 hours)
- Rename variables/functions for clarity
- Extract helper function from duplicated code
- Reorganize imports or file structure
- Example: Extract validation logic into helper function

### Medium Complexity (3-6 hours)
- Extract class from procedural code
- Split large module into multiple smaller modules
- Refactor complex function into pipeline/strategy pattern
- Example: Replace procedural orchestrator loop with OOP design

### High Complexity (1-2 days)
- Refactor entire component
- Change architectural patterns (e.g., procedural → OOP)
- Consolidate multiple modules with overlapping concerns
- May require coordinated test updates
- Example: Refactor validation system to use plugin architecture

### Epic Complexity (3+ days)
- Multi-component refactoring
- Architectural redesign
- Break into parent issue + child tasks
- Example: Migrate entire codebase to async/await

**For Epic-sized refactors:**
```bash
# Create parent refactor issue
bd create "Epic: Refactor validation to plugin architecture" -t epic -p 2 --json
bd label add <epic-id> refactor validation --json

# Create child tasks
bd create "Extract ValidationPlugin interface" -t task -p 2 --parent <epic-id> --json
bd create "Migrate coverage gate to plugin" -t task -p 2 --parent <epic-id> --json
bd create "Migrate linting gate to plugin" -t task -p 2 --parent <epic-id> --json
bd create "Add plugin discovery and registration" -t task -p 2 --parent <epic-id> --json
```

## Labels to Add
```bash
bd label add <issue-id> <component> refactor code-quality --json
```

**Common component labels:**
- `orchestrator` - Orchestration loop and workflow
- `validation` - Quality gates and validation
- `beads` - Beads integration
- `agents` - AI agent integration
- `worktrees` - Git worktree management

**Refactor-specific labels:**
- `code-quality` - General code quality improvement
- `tech-debt` - Paying down technical debt
- `extract-class` - OOP extraction
- `consolidation` - Combining duplicated code

## Example Issue Creation
```bash
bd create "Refactor orchestrator: extract retry logic into separate module" \
  -t task \
  -p 2 \
  -d "The orchestrator's retry logic is embedded in the main loop, making it hard to test and reuse. Extract into RetryStrategy class in new orchestration/retry.py module. No behavior changes, purely structural improvement." \
  --design "Create RetryStrategy abstract base class. Implement ExponentialBackoffRetry. Update orchestrator to use strategy pattern. Move retry tests to test_retry.py." \
  --acceptance "Retry logic isolated in retry.py. All existing tests pass. Integration tests verify behavior unchanged. Code is more testable and reusable." \
  --json

bd label add <issue-id> orchestrator refactor code-quality --json
```

## Anti-Patterns to Avoid
- ❌ Changing behavior while refactoring (do in separate commit)
- ❌ Refactoring without running tests continuously
- ❌ Making "while I'm here" unrelated changes
- ❌ Lowering test coverage during refactor
- ❌ Breaking backwards compatibility of public APIs
- ❌ Refactoring code you don't understand
- ❌ Not updating tests when internal structure changes
- ❌ Skipping integration tests ("it's just a refactor")

## Refactoring Best Practices

### The Refactoring Workflow
1. **Understand**: Read code thoroughly, ensure tests pass
2. **Baseline**: Document current behavior (run tests, note coverage)
3. **Small Steps**: Make tiny changes, run tests after each
4. **Preserve Behavior**: Tests must keep passing
5. **Commit Often**: Commit after each logical refactoring step
6. **Verify**: Final integration test to confirm behavior unchanged

### Safe Refactoring Techniques
- **Extract Method**: Pull code into new function
- **Rename**: Use IDE refactoring tools
- **Move**: Relocate functions/classes to better modules
- **Inline**: Remove unnecessary indirection
- **Replace Conditional with Polymorphism**: Use strategy/command patterns
- **Introduce Parameter Object**: Replace long parameter lists

### When to Stop
Stop refactoring if:
- Tests start failing unexpectedly
- You realize behavior needs to change (create separate issue)
- Code is "good enough" (perfect is enemy of done)
- Refactor scope is growing (break into subtasks)
