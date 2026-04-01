# Test Addition Template

## Title Pattern
`Add tests: [component/module] [specific area]`

**Examples:**
- `Add tests: orchestrator retry logic coverage`
- `Add tests: beads integration for edge cases`
- `Add tests: validation gates error handling`

## Issue Type
`task` (use `tests` label)

## Priority Guidelines
- **P0 (Critical)**: Critical path untested, blocking production release
- **P1 (High)**: Important functionality has low coverage (<50%)
- **P2 (Medium)**: Good coverage (50-79%) but missing edge cases
- **P3 (Low)**: Already good coverage (80%+), improving to excellent (95%+)

## Expected Files to Modify

### Testing Files
- `tests/[component]/test_[module].py` - Add unit tests
- `tests/integration/test_[workflow].py` - Add integration tests
- `tests/conftest.py` - Add fixtures if needed

### Source Files (Minimal)
- `src/pokepoke/[component]/[module].py` - ONLY if making testable (no behavior changes)

## Testing Approach

### Coverage Analysis First
```bash
# Check current coverage
pytest tests/[component]/ --cov=src/pokepoke/[component] --cov-report=html

# Open coverage/index.html to see uncovered lines
# Identify specific gaps: untested functions, missing edge cases, error paths
```

### Types of Tests to Add

#### 1. Unit Tests (Fast, Isolated)
```python
def test_function_with_valid_input():
    """Test happy path with valid inputs."""
    result = function(valid_input)
    assert result == expected_output

def test_function_with_invalid_input():
    """Test error handling with invalid inputs."""
    with pytest.raises(ValueError, match="Invalid"):
        function(invalid_input)

def test_function_with_edge_cases():
    """Test boundary conditions."""
    assert function([]) == []  # Empty input
    assert function(None) is None  # Null input
    assert function(large_input) == expected  # Large input
```

#### 2. Integration Tests (Slower, Real Dependencies)
```python
def test_full_workflow(tmp_path):
    """Test complete workflow end-to-end."""
    # Arrange: Setup real environment
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Act: Run workflow
    result = run_workflow(workspace)
    
    # Assert: Verify results
    assert result.success
    assert (workspace / "output.txt").exists()
```

#### 3. Error Path Tests
```python
def test_handles_network_failure():
    """Test graceful handling of network errors."""
    with patch('requests.get', side_effect=RequestException):
        result = fetch_data()
        assert result.error == "network_failure"

def test_handles_timeout():
    """Test timeout handling."""
    with patch('subprocess.run', side_effect=TimeoutExpired('cmd', 30)):
        result = run_command()
        assert result.error == "timeout"
```

#### 4. Edge Case Tests
```python
def test_handles_concurrent_access():
    """Test thread safety."""
    # Run same operation from multiple threads
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(operation) for _ in range(10)]
        results = [f.result() for f in futures]
    
    # All should succeed, no race conditions
    assert all(r.success for r in results)
```

### Test Coverage Target
- **Modified files**: 80%+ line coverage (enforced by pre-commit hook)
- **Critical paths**: 100% coverage
- **Error paths**: All error handling tested
- **Edge cases**: Empty, null, boundary values tested

## Acceptance Criteria

### Coverage Improvements
- [ ] Coverage increased from baseline (check coverage report)
- [ ] All critical paths are tested
- [ ] Error handling is tested for all error types
- [ ] Edge cases are covered (empty, null, boundary values)

### Test Quality
- [ ] Tests are clear and well-documented
- [ ] Tests follow AAA pattern (Arrange, Act, Assert)
- [ ] Tests are independent (no shared state)
- [ ] Tests run fast (unit tests <1s each)
- [ ] Tests are deterministic (no flaky tests)

### Test Organization
- [ ] Tests are in correct location (unit vs integration)
- [ ] Test file names match module names
- [ ] Fixtures are in conftest.py if shared
- [ ] Test names clearly describe what they test

### Quality Gates
- [ ] All tests pass (including new tests)
- [ ] Pre-commit hooks pass (80%+ coverage on modified files)
- [ ] No new linting or type checking warnings
- [ ] Git status clean (all changes committed)

## Complexity Guidelines

### Low Complexity (1-2 hours)
- Add 5-10 tests to existing test file
- Cover missing edge cases for single function
- Add error handling tests
- Example: Add null/empty input tests for validation function

### Medium Complexity (3-6 hours)
- Create new test file for untested module
- Add 20-30 tests covering full module
- Add integration tests for workflow
- Example: Create test suite for new beads query module

### High Complexity (1-2 days)
- Add comprehensive test coverage for component
- Create complex integration tests with real dependencies
- Add performance/load tests
- Example: Full integration test suite for orchestrator with mocks

### Epic Complexity (3+ days)
- Increase entire codebase coverage from <50% to 80%+
- Add comprehensive integration test suite
- Break into multiple issues per component
- Example: Project-wide test coverage improvement initiative

**For Epic-sized test additions:**
```bash
# Create parent test improvement issue
bd create "Epic: Improve test coverage to 80%+" -t epic -p 1 --json
bd label add <epic-id> tests tech-debt --json

# Create child tasks per component
bd create "Add tests: orchestrator coverage" -t task -p 1 --parent <epic-id> --json
bd create "Add tests: validation coverage" -t task -p 1 --parent <epic-id> --json
bd create "Add tests: beads integration coverage" -t task -p 1 --parent <epic-id> --json
```

## Labels to Add
```bash
bd label add <issue-id> <component> tests code-quality --json
```

**Common component labels:**
- `orchestrator` - Orchestration loop and workflow
- `validation` - Quality gates and validation
- `beads` - Beads integration
- `agents` - AI agent integration
- `worktrees` - Git worktree management

**Test-specific labels:**
- `tests` - Test addition/improvement
- `coverage` - Coverage improvement
- `tech-debt` - Paying down technical debt

## Example Issue Creation
```bash
bd create "Add tests: orchestrator retry logic coverage" \
  -t task \
  -p 1 \
  -d "The orchestrator's retry logic is only ~40% covered. Add tests for: exponential backoff calculation, max retry limit enforcement, retry on transient vs permanent errors, retry state persistence across restarts." \
  --acceptance "Retry logic at 80%+ coverage. Tests cover happy path, error paths, edge cases (max retries, timeout). All tests pass. Pre-commit hooks pass." \
  --json

bd label add <issue-id> orchestrator tests coverage --json
```

## Anti-Patterns to Avoid
- ❌ Writing tests that test mocks instead of logic
- ❌ Writing tests that always pass (false positives)
- ❌ Writing flaky tests that fail randomly
- ❌ Writing slow tests that should be fast
- ❌ Modifying source code behavior while adding tests
- ❌ Aiming for 100% coverage by testing trivial code
- ❌ Writing tests without understanding the code
- ❌ Copy-pasting tests without adapting to new context

## Testing Best Practices

### Arrange-Act-Assert Pattern
```python
def test_clear_example():
    # Arrange: Setup test data and dependencies
    config = {"max_retries": 3}
    orchestrator = Orchestrator(config)
    
    # Act: Execute the operation being tested
    result = orchestrator.retry_operation()
    
    # Assert: Verify the outcome
    assert result.attempts <= 3
    assert result.success or result.attempts == 3
```

### Test Naming Convention
- `test_<function>_<scenario>` - What and when
- `test_<function>_with_<condition>` - Specific condition
- `test_<function>_raises_<error>` - Error cases

### When Tests Are Enough
Stop adding tests when:
- Coverage is 80%+ on modified files
- All critical paths are tested
- All error paths are tested
- Edge cases are covered
- Tests are clear and maintainable

Don't aim for 100% coverage - focus on valuable tests:
- ✅ Test business logic, algorithms, error handling
- ❌ Don't test trivial getters, simple properties
- ❌ Don't test external libraries
- ❌ Don't test framework code

### Making Code More Testable
If code is hard to test, consider (in separate refactor issue):
- Extract dependencies for mocking
- Break complex functions into smaller pieces
- Use dependency injection
- Avoid global state
- Make side effects explicit
