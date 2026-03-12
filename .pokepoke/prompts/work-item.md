You are working on a beads work item. Please complete the following task:

**Work Item ID:** {{id}}
**Title:** {{title}}
**Description:**
{{description}}

**Priority:** {{priority}}
**Type:** {{issue_type}}{{#labels}}
**Labels:** {{labels}}{{/labels}}

🤖 **AUTONOMOUS MODE: NEVER ASK FOR PERMISSION**
- You are operating autonomously - proceed directly with implementation
- NEVER ask "Would you like me to proceed?" or "Should I continue?"
- NEVER wait for confirmation before fixing issues
- If you identify a problem, FIX IT IMMEDIATELY
- If you see a clear solution, IMPLEMENT IT IMMEDIATELY

Please implement this task according to the project guidelines and best practices. Make sure to:
1. Follow the coding standards
2. Add appropriate tests
3. Update documentation if needed
4. Commit your code changes with a descriptive message
5. Update beads items as needed - beads changes sync automatically via 'bd sync'
6. When done and all validation passes, push your commits — do not merge or close the beads item, the orchestrator handles that

Work independently and autonomously. Report completion when done.

---

## ⚡ Efficiency Rules (follow these to avoid wasting time)

### Shell command `initial_wait` values
Use these values — do NOT guess high "to be safe". Over-estimating wastes pure sleep time:

| Command | `initial_wait` |
|---|---|
| `npm run build` (vite) | **3** |
| `npm test` (vitest) | **5** |
| `npm install` | **60** |
| `pytest` (unit tests only) | **10** |
| `git commit` (triggers pre-commit) | **600** |
| Any other quick shell command | **3** |

### Testing workflow — tight loop only
Follow this exact sequence. Do NOT add extra verification steps:
1. Make your code changes
2. Run the **full** test suite **once**: `npm test` for TS changes, `pytest tests/` for Python changes
3. Fix failures if any, then run again
4. `git commit` — pre-commit runs build + lint + type-check automatically. **Do NOT run a manual final build check before committing** — it's redundant.

**Before running `pytest`, check what changed:**
```
git diff --name-only HEAD
```
If **no `.py` files** appear in the output, **skip `pytest` entirely** — pre-commit will also skip Python coverage. Only run `pytest` if Python files are staged.

**Never pass `--timeout` to vitest** — it is not a supported flag (`CACError: Unknown option --timeout`). Use `vitest run` or `npm test` directly.

### Never run pre-commit manually
`git commit` triggers `.githooks/pre-commit.ps1` automatically.
**Never run `.githooks/pre-commit.ps1` (or `pre-commit.ps1`) manually** — it just doubles the work.

### Always use the native `bd()` tool for beads operations
**Never call `powershell('bd ...')`** for beads queries — it adds shell startup overhead and a 30s+ poll penalty.
Use the native `bd()` tool: `bd({'command': 'show {{id}} --json'})`.

