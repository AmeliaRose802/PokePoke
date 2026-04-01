# Documentation Template

## Title Pattern
`Docs: [area] [brief description]`

**Examples:**
- `Docs: Add feature spec for parallel agent execution`
- `Docs: Update README with template system usage`
- `Docs: Clarify validation gate retry behavior`

## Issue Type
`task` (use `documentation` label)

## Priority Guidelines
- **P0 (Critical)**: Production feature undocumented, blocking users
- **P1 (High)**: Important feature poorly documented, causing confusion
- **P2 (Medium)**: Feature documented but needs improvement/examples
- **P3 (Low)**: Nice-to-have docs, clarifications, minor updates

## Expected Files to Modify

### User-Facing Documentation
- `README.md` - Main project documentation
- `docs/feature_specs/[feature-name].md` - Feature specifications

### Developer Documentation
- `.github/copilot-instructions.md` - Agent instructions
- Code comments - Docstrings and inline comments
- `tests/README.md` - Testing documentation (if applicable)

### Configuration Documentation
- `.pokepoke/config.yaml` - Configuration comments
- Example files - Sample configurations

## Documentation Approach

### Types of Documentation

#### 1. README Updates (User-Facing)
```markdown
## Feature Name

Brief description of what the feature does and why it's useful.

### Usage

\`\`\`bash
# Basic usage
command --flag value

# Advanced usage
command --flag value --option another
\`\`\`

### Configuration

Add to `.pokepoke/config.yaml`:

\`\`\`yaml
feature:
  option1: value1
  option2: value2
\`\`\`

### Examples

**Example 1: Common use case**
\`\`\`bash
command --example
\`\`\`

**Example 2: Advanced use case**
\`\`\`bash
command --advanced --example
\`\`\`
```

#### 2. Feature Specs (Detailed Design)
```markdown
# Feature Name

**Status:** Implemented | In Progress | Planned
**Version:** vX.Y.Z
**Author:** Name
**Date:** YYYY-MM-DD

## Overview

2-3 sentence summary of what this feature does and why it exists.

## Purpose

Detailed explanation of the problem this solves and use cases.

## User-Facing Behavior

How users interact with this feature. Include:
- How to enable/configure
- What happens when invoked
- Expected output or side effects

## Implementation Details

For developers who need to maintain or extend this feature:
- Architecture decisions
- Key modules and their responsibilities
- Integration points with other components

## Examples

### Example 1: Basic Usage
\`\`\`bash
command
\`\`\`

### Example 2: Advanced Usage
\`\`\`bash
command --advanced
\`\`\`

## Configuration

Document all configuration options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `option1` | `string` | `"default"` | What it does |
| `option2` | `int` | `10` | What it does |

## Troubleshooting

Common issues and solutions:

**Issue:** Description
**Solution:** How to fix

## Future Improvements

Ideas for extending this feature (optional).
```

#### 3. Agent Instructions (AI Context)
```markdown
## Feature Name

**When to use:** Describe scenarios where agent should use this feature

**Usage:**
\`\`\`bash
command --flag value
\`\`\`

**Important notes:**
- Critical things agents should know
- Common pitfalls to avoid
- Best practices

**Example:**
\`\`\`bash
# Concrete example of typical usage
command --example
\`\`\`
```

#### 4. Code Comments (Inline)
```python
class FeatureName:
    """Brief one-line description.
    
    Longer description explaining purpose, usage, and important details.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value
    
    Raises:
        ValueError: When this happens
        TypeError: When that happens
    
    Example:
        >>> feature = FeatureName(param1="value")
        >>> result = feature.execute()
        >>> result.success
        True
    """
    
    def complex_method(self, input: str) -> Result:
        """Brief description of what method does.
        
        More detailed explanation if needed.
        """
        # Explain WHY, not WHAT (code shows what)
        # Use this if input contains special characters
        sanitized = self._sanitize(input)
        
        # Retry logic: exponential backoff up to 3 attempts
        for attempt in range(3):
            try:
                return self._execute(sanitized)
            except TransientError:
                time.sleep(2 ** attempt)
        
        raise PermanentError("All retries exhausted")
```

## Acceptance Criteria

### Documentation Quality
- [ ] Documentation is clear and concise
- [ ] Examples are provided for all features
- [ ] All configuration options are documented
- [ ] Troubleshooting section for common issues (if applicable)

### Accuracy
- [ ] Documentation matches current implementation
- [ ] Code examples are tested and work
- [ ] Configuration examples are valid
- [ ] Links are correct and not broken

### Completeness
- [ ] User-facing features in README
- [ ] Complex features have feature specs
- [ ] Agent instructions updated if behavior affects agents
- [ ] Code comments explain complex logic

### Quality Gates
- [ ] Markdown linting passes (if applicable)
- [ ] Spelling and grammar checked
- [ ] Formatting is consistent
- [ ] Git status clean (all changes committed)

**Note:** Documentation changes typically don't require tests, but configuration examples should be validated.

## Complexity Guidelines

### Low Complexity (30-60 minutes)
- Update README with small change
- Add clarifying comments to code
- Fix typos or broken links
- Example: Add usage example to README

### Medium Complexity (1-3 hours)
- Create new feature spec document
- Update README with new feature section
- Add comprehensive code documentation to module
- Example: Document new validation gate system

### High Complexity (4+ hours)
- Comprehensive documentation overhaul
- Multiple feature specs
- Update user guide, developer guide, and agent instructions
- Example: Document entire orchestrator architecture

## Labels to Add
```bash
bd label add <issue-id> documentation <component> --json
```

**Common component labels:**
- `orchestrator` - Orchestration loop and workflow
- `validation` - Quality gates and validation
- `beads` - Beads integration
- `agents` - AI agent integration
- `config` - Configuration management

**Documentation-specific labels:**
- `documentation` - Documentation work
- `user-facing` - User-facing documentation
- `developer-docs` - Developer documentation
- `examples` - Example code/configs

## Example Issue Creation

### Feature Documentation
```bash
bd create "Docs: Add feature spec for parallel agent execution" \
  -t task \
  -p 2 \
  -d "The parallel agent execution feature is implemented but not documented. Create feature spec in docs/feature_specs/parallel-agents.md covering: purpose, configuration, how it works, examples, troubleshooting." \
  --acceptance "Feature spec created with comprehensive coverage. README updated with usage section. Agent instructions updated with best practices." \
  --json

bd label add <issue-id> documentation orchestrator agents --json
```

### README Update
```bash
bd create "Docs: Update README with template system usage" \
  -t task \
  -p 1 \
  -d "Add section to README explaining beads template system: what templates are available, how to use them when creating issues, examples of each template." \
  --acceptance "README has templates section with clear examples. Users can understand how to use templates." \
  --json

bd label add <issue-id> documentation beads user-facing --json
```

### Code Documentation
```bash
bd create "Docs: Clarify validation gate retry behavior" \
  -t task \
  -p 2 \
  -d "Add comprehensive docstrings to validation gate classes explaining retry logic, backoff strategy, when retries stop. Add inline comments explaining complex retry logic in _execute_with_retry()." \
  --acceptance "All validation gate classes have complete docstrings. Complex retry logic has explanatory comments. Developer can understand retry behavior from code." \
  --json

bd label add <issue-id> documentation validation developer-docs --json
```

## Anti-Patterns to Avoid
- ❌ Writing documentation for unimplemented features
- ❌ Copy-pasting documentation from other projects
- ❌ Including outdated examples that don't work
- ❌ Writing documentation without testing examples
- ❌ Using jargon without explanation
- ❌ Writing walls of text without examples
- ❌ Documenting internal implementation details in user docs
- ❌ Committing documentation with broken links

## Documentation Best Practices

### Writing Style
- **Be concise**: Get to the point quickly
- **Use examples**: Show, don't just tell
- **Be specific**: "Set max_retries to 3" not "Configure retries appropriately"
- **Use active voice**: "The system retries 3 times" not "3 retries are performed"
- **Avoid jargon**: Explain technical terms or use simpler language

### Structure
- **Start with overview**: Brief summary at the top
- **Progressive detail**: Overview → Details → Examples → Reference
- **Use headings**: Make it scannable
- **Use lists**: Break up dense text
- **Use code blocks**: Format code/configs properly

### Examples
- **Always include examples**: Real-world usage
- **Test examples**: Make sure they work
- **Show output**: What users should expect to see
- **Cover common cases**: Not just happy path

### Maintenance
- **Update with code**: Document while implementing
- **Review regularly**: Check docs still match code
- **Remove outdated**: Delete docs for removed features
- **Version appropriately**: Note when features were added

### Audience
- **README**: End users, getting started
- **Feature Specs**: Developers, detailed design
- **Agent Instructions**: AI agents, task-specific context
- **Code Comments**: Maintainers, implementation details
