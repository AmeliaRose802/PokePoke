# Allowed Directories Feature

## Overview

The PokePoke orchestrator now includes runtime directory restriction support to prevent Copilot from getting stuck when trying to access directories outside the repository.

## How It Works

### Template-Based Approach

The `beads-item.md` prompt template includes a section that dynamically lists allowed directories:

```markdown
**Allowed Directories (you can ONLY access these):**
{{#allowed_directories}}
- `{{.}}`
{{/allowed_directories}}
```

### Runtime Directory Detection

When building a prompt, the system automatically detects:

1. **Current Directory** - The worktree or main repo where code is being edited
2. **Main Repository Root** - The parent repository (for merging back)

These are added to the `--add-dir` flags when invoking Copilot CLI.

## Usage

### Using the Template Function

```python
from pokepoke.copilot import build_prompt_from_template
from pokepoke.types import BeadsWorkItem

# Create a work item
item = BeadsWorkItem(
    id="PokePoke-123",
    title="Fix authentication bug",
    description="Fix the OAuth token refresh logic",
    issue_type="bug",
    priority=1,
    labels=["security", "backend"]
)

# Build prompt with allowed directories injected
prompt = build_prompt_from_template(item, template_name="beads-item")

# The prompt will include the allowed directories automatically
```

### Manual Directory List

You can also get the allowed directories independently:

```python
from pokepoke.copilot import get_allowed_directories

allowed = get_allowed_directories()
# Returns: ['C:\\Users\\username\\PokePoke\\worktrees\\task-123', 'C:\\Users\\username\\PokePoke']
```

## Template Syntax

The prompt service supports Mustache-like array iteration:

- `{{#array_name}}` - Start array iteration
- `{{.}}` - Current item in the array
- `{{/array_name}}` - End array iteration

## Example Output

When rendered, the beads-item template produces:

```markdown
**⚠️ CRITICAL: DIRECTORY ACCESS RESTRICTIONS**

YOU MUST NEVER ATTEMPT TO ACCESS ANY DIRECTORY OUTSIDE THE ALLOWED DIRECTORIES!

**Allowed Directories (you can ONLY access these):**
- `C:\Users\ameliapayne\PokePoke\worktrees\PokePoke-123`
- `C:\Users\ameliapayne\PokePoke`

**DO NOT access:**
- Parent directories outside the repo
- System directories (C:\Windows, /etc, /usr, etc.)
- User home directories
- Any path not explicitly listed above
```

## Benefits

1. **Prevents Hangs** - Copilot won't get stuck trying to access forbidden directories
2. **Clear Boundaries** - Explicit list of what's accessible
3. **Dynamic** - Automatically adapts to worktree vs main repo context
4. **Safe** - Matches the directories passed to `--add-dir` in Copilot CLI invocation

## Integration with Copilot CLI

The `invoke_copilot_cli` function in [copilot.py](c:\Users\ameliapayne\PokePoke\src\pokepoke\copilot.py#L184-L192) automatically:

1. Detects current directory (worktree)
2. Detects main repository root
3. Passes both as `--add-dir` arguments to Copilot CLI

This ensures consistency between what the prompt says and what Copilot CLI enforces.

## Testing

Tests are included in `tests/test_prompts.py`:

- `test_render_array_iteration` - Tests array rendering
- `test_render_beads_item_with_directories` - Tests full template with directories

Run tests with:

```bash
python -m pytest tests/test_prompts.py -v
```
