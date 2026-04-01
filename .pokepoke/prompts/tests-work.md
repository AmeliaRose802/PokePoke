{{>beads-item}}

## 🧪 Testing Context

This work item is related to **tests** - unit tests, integration tests, or testing infrastructure.

### Key Files

- `tests/` - All test files
- `tests/models/` - Model and SDK tests
- `tests/orchestration/` - Orchestrator tests
- `tests/desktop/` - UI tests
- `pytest.ini` - Pytest configuration
- `.githooks/check-coverage.py` - Coverage enforcement

### Testing Standards

**Coverage Requirements:**
- Minimum 80% line coverage on all modified files
- Pre-commit hooks enforce coverage automatically
- Focus on happy paths, error handling, and edge cases

**Test Organization:**
- Unit tests: Fast, isolated, mocked dependencies
- Integration tests: Test component interactions
- Use fixtures for common setup
- Use parametrize for testing multiple scenarios

### Running Tests

**Full test suite:**
```powershell
pytest --timeout={{command_timeout}}
```

**Specific test file:**
```powershell
pytest tests/test_specific.py --timeout={{command_timeout}}
```

**Coverage report:**
```powershell
pytest --cov=src --cov-report=term-missing --timeout={{command_timeout}}
```

**Watch mode during development:**
```powershell
pytest --watch
```

### Writing Good Tests

**Test Structure (Arrange-Act-Assert):**
```python
def test_feature():
    # Arrange - Set up test data and mocks
    mock_service = Mock()
    mock_service.method.return_value = "expected"
    
    # Act - Execute the code under test
    result = feature_function(mock_service)
    
    # Assert - Verify the outcome
    assert result == "expected"
    mock_service.method.assert_called_once()
```

**Mock External Dependencies:**
- Mock file I/O, network calls, subprocesses
- Use `unittest.mock` or `pytest-mock`
- Verify mock interactions with `assert_called_with()`

### Common Pitfalls

- ⚠️ Don't skip coverage checks - they're enforced in CI
- ⚠️ Don't forget to test error paths and edge cases
- ⚠️ Don't write flaky tests - ensure deterministic behavior
- ⚠️ Don't test implementation details - test behavior
- ⚠️ Mock external dependencies to keep tests fast and isolated
