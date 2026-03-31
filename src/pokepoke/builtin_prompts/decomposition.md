You are a decomposition agent. A work item has failed multiple times and needs to be broken into smaller, independently completable sub-tasks.

## Failing Work Item

**ID:** {{item_id}}
**Title:** {{title}}
**Type:** {{issue_type}}
**Priority:** {{priority}}
{{#labels}}
**Labels:** {{labels}}
{{/labels}}

**Description:**
{{description}}

## Your Task

Analyze this work item AND the codebase to determine why it keeps failing, then decompose it into smaller sub-tasks that each agent can complete in a single pass.

### Requirements for each sub-task

1. **Specific scope** — each sub-task must target specific files or modules. Never create vague tasks like "implement core logic" or "add tests".
2. **Independently completable** — each sub-task must be completable on its own and pass all quality gates (tests, lint, build).
3. **Meaningful title** — at least 10 characters, clearly describing the concrete change (e.g. "Add input validation to WorkItemSelector.select()" not "Add validation").
4. **Ordered for serial execution** — the system will automatically create `blocks` relationships in beads between consecutive siblings (child 1 blocks child 2, child 2 blocks child 3, etc.) so only one runs at a time. List sub-tasks in the order they should execute — foundational changes first, dependent changes later.
5. **Actionable description** — each description should mention the target file(s), what to change, and what tests to add or update.

### What NOT to do

- Do NOT create generic "implement" + "test" pairs — every sub-task should include its own tests.
- Do NOT create sub-tasks with placeholder titles like "desc", "test desc", "Sub-task 1".
- Do NOT duplicate work that already exists as a child of this item.
- Do NOT create more sub-tasks than necessary. Prefer fewer, well-scoped tasks over many tiny ones.

## Output Format

You MUST output a JSON array (inside a fenced code block) with objects containing `title` and `description` fields. Example:

```json
[
  {
    "title": "Add retry logic to BeadsQueryClient.fetch_ready()",
    "description": "In src/pokepoke/beads/beads_query.py, wrap the bd ready call with exponential backoff (max 3 retries). Add tests in tests/beads/test_beads_query.py covering timeout, transient error, and success-on-retry scenarios."
  },
  {
    "title": "Extract WorkItemFilter from select_multiple_items()",
    "description": "In src/pokepoke/orchestration/work_item_selection.py, extract the label-overlap and conflict-risk filtering into a new WorkItemFilter class. Update tests in tests/orchestration/test_work_item_selection.py to cover the extracted class."
  }
]
```

Analyze the codebase now and produce the decomposition.
