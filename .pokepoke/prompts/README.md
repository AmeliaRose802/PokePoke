# Prompt Template System

This directory contains prompt templates used by PokePoke for Copilot CLI invocations.

## Overview

All prompts are now **loaded from template files** instead of being hardcoded in Python code. This makes prompts easier to:
- Edit without touching code
- Version control separately
- Share and reuse across tools
- Test and validate independently

## Template Syntax

Templates use **Mustache-like syntax**:

### Variable Substitution

```markdown
Hello {{name}}, your ID is {{id}}.
```

Variables are replaced with values from the context dictionary.

### Conditional Sections

```markdown
{{#labels}}
**Labels:** {{labels}}
{{/labels}}
```

Conditional sections only render when the variable is truthy (not `None`, `False`, `""`, etc.).

### Template Inheritance

```markdown
{{>base-template}}

Additional content here...
```

Templates can include other templates using `{{>template-name}}` syntax. This allows you to extend base templates with additional content.

## Available Templates

### `beads-item.md`

Main work item prompt for task execution (formerly `work-item.md`).

**Variables:**
- `item_id` - Work item ID (e.g., "PokePoke-123")
- `title` - Work item title
- `description` - Work item description
- `priority` - Priority level (0-4)
- `issue_type` - Type (bug, feature, task, etc.)
- `labels` - Comma-separated labels (optional)
- `command_timeout` - Command timeout in seconds
- `retry_feedback` - Feedback from previous attempts (optional)
- `mcp_enabled` - Whether MCP server is enabled (boolean)
- `test_data_section` - Test data section content (optional)

### Label-Specific Templates

Custom templates can be selected based on work item labels. Configure in `.pokepoke/config.yaml`:

```yaml
prompt_templates:
  orchestrator: "orchestrator-work"
  desktop: "desktop-work"
  tests: "tests-work"
```

When a work item has a label matching a key in `prompt_templates`, that template will be used instead of the default `beads-item.md`.

**Example templates provided:**

#### `orchestrator-work.md`
- Extends `beads-item.md` with orchestrator-specific context
- Lists key orchestrator files
- Documents common patterns (beads integration, worktree management)
- Highlights common pitfalls

#### `desktop-work.md`
- Extends `beads-item.md` with desktop/TUI context
- Lists key UI component files
- Documents UI patterns and state management
- Includes testing guidelines for UI changes

#### `tests-work.md`
- Extends `beads-item.md` with testing context
- Documents coverage requirements (80%+)
- Shows test organization and running tests
- Provides testing best practices and mock patterns

### Creating Label-Specific Templates

1. **Create template file**: `<label>-work.md` in this directory
2. **Extend base template**: Start with `{{>beads-item}}` to include all base content
3. **Add label-specific content**: Add sections with context, files, patterns, pitfalls
4. **Configure mapping**: Add to `prompt_templates` in config file
5. **Test**: Create a work item with that label and verify the prompt

**Template structure example:**

```markdown
{{>beads-item}}

## 📋 [Domain] Context

Brief description of this domain/area.

### Key Files

- `path/to/file.py` - Description
- `path/to/other.py` - Description

### Common Patterns

**Pattern Name:**
- Description of pattern
- When to use it
- Example or reference

### Common Pitfalls

- ⚠️ Pitfall description
- ⚠️ Another pitfall
```

### `work-item-retry.md`

Enhanced prompt for retry attempts with validation feedback.

**Variables:**
- All from `work-item.md`, plus:
- `retry_context` - Boolean to show/hide retry section
- `attempt` - Current attempt number
- `max_retries` - Maximum retry attempts
- `errors` - Formatted error list from previous attempt

## Usage in Code

### Loading Prompts

```python
from pokepoke.prompts import get_prompt_service

# Get service instance
service = get_prompt_service()

# Load and render template
prompt = service.load_and_render("work-item", {
    "id": "PokePoke-123",
    "title": "Fix bug",
    "description": "Fix the authentication issue",
    "priority": 1,
    "issue_type": "bug",
    "labels": "security, urgent"
})
```

### Creating New Templates

1. **Create template file**: `<template-name>.md` in this directory
2. **Use template syntax**: Add variables with `{{variable}}` and conditionals with `{{#section}}...{{/section}}`
3. **Load in code**: `service.load_and_render("template-name", variables)`
4. **Add tests**: Update `tests/test_prompts.py` with test cases

## Template Guidelines

**DO:**
- [OK] Use descriptive variable names
- [OK] Document required vs optional variables
- [OK] Include context and requirements in prompts
- [OK] Test templates with real data
- [OK] Keep templates focused and single-purpose

**DON'T:**
- [FAIL] Hardcode prompts in Python code
- [FAIL] Use complex logic in templates (keep it simple)
- [FAIL] Forget to handle missing/optional variables
- [FAIL] Mix multiple concerns in one template

## Testing

Templates are tested in `tests/test_prompts.py`:

```bash
python -m pytest tests/test_prompts.py -v
```

Tests verify:
- Template loading
- Variable substitution
- Conditional sections
- Missing variable handling
- Integration with work item data

## Migration from Hardcoded Prompts

**Before:**
```python
def build_prompt(work_item):
    return f"""You are working on {work_item.id}
    Title: {work_item.title}
    ..."""
```

**After:**
```python
def build_prompt(work_item):
    service = get_prompt_service()
    return service.load_and_render("work-item", {
        "id": work_item.id,
        "title": work_item.title,
        ...
    })
```

## Related Files

- [`pokepoke/prompts.py`](../pokepoke/prompts.py) - Prompt loading service implementation
- [`tests/test_prompts.py`](../tests/test_prompts.py) - Prompt system tests
- [`.github/prompts/`](../.github/prompts/) - Additional agent prompts

