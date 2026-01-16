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

## Available Templates

### `work-item.md`

Basic work item prompt for first-time task execution.

**Variables:**
- `id` - Work item ID (e.g., "PokePoke-123")
- `title` - Work item title
- `description` - Work item description
- `priority` - Priority level (0-4)
- `issue_type` - Type (bug, feature, task, etc.)
- `labels` - Comma-separated labels (optional)

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
- ✅ Use descriptive variable names
- ✅ Document required vs optional variables
- ✅ Include context and requirements in prompts
- ✅ Test templates with real data
- ✅ Keep templates focused and single-purpose

**DON'T:**
- ❌ Hardcode prompts in Python code
- ❌ Use complex logic in templates (keep it simple)
- ❌ Forget to handle missing/optional variables
- ❌ Mix multiple concerns in one template

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
