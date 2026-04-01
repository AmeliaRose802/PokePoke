# Feature Template

## Title Pattern
`Add [component]: [brief description of feature]`

**Examples:**
- `Add orchestrator: parallel agent execution support`
- `Add validation: configurable retry limits per gate type`
- `Add beads: template system for common work types`

## Issue Type
`feature`

## Priority Guidelines
- **P0 (Critical)**: Blocking other high-priority work, customer commitment
- **P1 (High)**: Significant value, requested by multiple stakeholders
- **P2 (Medium)**: Nice to have, improves workflow efficiency
- **P3 (Low)**: Future enhancement, experimental

## Expected Files to Modify

### Primary Implementation
- `src/pokepoke/[component]/[new_module].py` - Main feature implementation
- `src/pokepoke/[component]/__init__.py` - Export new public API

### Configuration
- `.pokepoke/config.yaml` - Add configuration options if applicable
- `src/pokepoke/config.py` - Add config schema/validation

### Testing
- `tests/[component]/test_[new_module].py` - Comprehensive unit tests
- `tests/integration/test_[feature].py` - End-to-end integration tests

### Documentation
- `README.md` - Document user-facing usage
- `docs/feature_specs/[feature-name].md` - Detailed feature specification
- `.github/copilot-instructions.md` - Add agent instructions if relevant

## Testing Approach

### Required Tests
1. **Unit Tests**: Test each component in isolation with mocks
2. **Integration Tests**: Test feature end-to-end with real dependencies
3. **Edge Cases**: Test boundary conditions, error paths, invalid inputs
4. **Backwards Compatibility**: Ensure existing workflows still work

### Test Coverage Target
- **New files**: 80%+ line coverage (enforced by pre-commit hook)
- **Critical paths**: 100% coverage of main feature logic
- **Error handling**: All error paths must be tested

### Example Test Structure
```python
class TestNewFeature:
    """Comprehensive tests for new feature."""
    
    def test_feature_happy_path(self):
        """Test feature with valid inputs and expected usage."""
        # Arrange
        feature = NewFeature(config={"enabled": True})
        
        # Act
        result = feature.execute(valid_input)
        
        # Assert
        assert result.success
        assert result.data == expected_output
    
    def test_feature_handles_invalid_input(self):
        """Test feature gracefully handles invalid inputs."""
        feature = NewFeature()
        
        with pytest.raises(ValueError, match="Invalid input"):
            feature.execute(invalid_input)
    
    def test_feature_respects_configuration(self):
        """Test feature uses configuration correctly."""
        config = {"max_retries": 3, "timeout": 30}
        feature = NewFeature(config=config)
        
        assert feature.max_retries == 3
        assert feature.timeout == 30
    
    def test_feature_integration(self, tmp_path):
        """End-to-end integration test with real dependencies."""
        # Arrange: Setup real environment
        workspace = tmp_path / "test_workspace"
        workspace.mkdir()
        
        # Act: Run complete workflow
        result = run_feature_workflow(workspace)
        
        # Assert: Verify end-to-end behavior
        assert result.success
        assert (workspace / "output.txt").exists()
```

## Acceptance Criteria

### Functionality
- [ ] Feature implements all requirements from specification
- [ ] Feature is configurable via `.pokepoke/config.yaml`
- [ ] Feature integrates with existing workflows without breaking them
- [ ] Feature provides clear error messages on failure

### Code Quality
- [ ] Code follows existing patterns and conventions
- [ ] No code duplication (DRY principle)
- [ ] Functions are focused and well-named
- [ ] Complex logic has explanatory comments

### Testing
- [ ] Unit tests cover all new code paths (80%+ coverage)
- [ ] Integration tests verify end-to-end workflows
- [ ] All existing tests pass (no regressions)
- [ ] Edge cases and error paths are tested

### Documentation
- [ ] Feature spec created in `docs/feature_specs/`
- [ ] README updated with usage examples
- [ ] Agent instructions updated if feature affects agent behavior
- [ ] Code comments explain complex logic

### Quality Gates
- [ ] Pre-commit hooks pass (tests, coverage, linting, type checking)
- [ ] No new linting or type checking warnings
- [ ] Git status clean (all changes committed)
- [ ] Feature works in both interactive and autonomous modes

## Complexity Guidelines

### Low Complexity (2-4 hours)
- Adds a new utility function or helper
- Small enhancement to existing feature
- Single file, minimal dependencies
- Example: Add new config option with default behavior

### Medium Complexity (1-2 days)
- New component with clear boundaries
- Integrates with 2-3 existing components
- Requires new tests and documentation
- Example: Add retry strategy for validation gates

### High Complexity (3+ days)
- Major architectural addition
- Touches many components
- Requires significant testing and documentation
- May need to refactor existing code
- Example: Add multi-agent parallel execution support

### Epic/Multi-Issue Complexity (1+ weeks)
- Feature too large for single PR
- Break into parent issue + child tasks
- Each child should be independently testable
- Example: Add full support for alternative AI backend

**For Epic-sized features:**
```bash
# Create parent feature issue
bd create "Epic: Add alternative AI backend support" -t epic -p 1 --json

# Create child tasks
bd create "Add backend abstraction interface" -t task -p 1 --parent <epic-id> --json
bd create "Implement Claude Code backend" -t task -p 1 --parent <epic-id> --json
bd create "Add backend selection config" -t task -p 1 --parent <epic-id> --json
bd create "Add integration tests for backends" -t task -p 1 --parent <epic-id> --json
```

## Labels to Add
```bash
bd label add <issue-id> <component> feature --json
```

**Common component labels:**
- `orchestrator` - Orchestration loop and workflow
- `validation` - Quality gates and validation
- `beads` - Beads integration
- `agents` - AI agent integration
- `config` - Configuration management
- `worktrees` - Git worktree management

## Example Issue Creation
```bash
bd create "Add validation: configurable retry limits per gate type" \
  -t feature \
  -p 2 \
  -d "Allow configuring different retry limits for different gate types (e.g., fast gates retry more, slow gates retry less). Add config in .pokepoke/config.yaml under validation.retry_limits with per-gate overrides." \
  --design "Add ValidationConfig dataclass with gate_retry_limits: Dict[str, int]. Update validation runner to check config before retrying. Default to global retry_limit if gate-specific not configured." \
  --acceptance "Config supports per-gate retry limits. Existing behavior unchanged (uses global default). Integration tests verify gate-specific limits work." \
  --json

bd label add <issue-id> validation feature --json
```

## Anti-Patterns to Avoid
- ❌ Implementing features without specification/design
- ❌ Adding features that break existing workflows
- ❌ Skipping tests because "it's a small feature"
- ❌ Hard-coding values instead of making them configurable
- ❌ Not documenting user-facing changes
- ❌ Creating monolithic features (break into subtasks)
- ❌ Lowering quality gates to "ship faster"
