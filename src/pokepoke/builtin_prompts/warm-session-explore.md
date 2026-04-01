# Warm Session Exploration — {{label}}

You are pre-warming a session for the **{{label}}** code area. Your goal is to quickly explore and internalize the codebase structure so future work items with this label can start with context already loaded.

## Exploration Goals

1. **Identify key files and modules** related to "{{label}}"
2. **Understand the module layout** — where are the main source files, tests, and configs?
3. **Note important patterns** — coding conventions, testing approaches, key abstractions
4. **Map dependencies** — what does this code area depend on and what depends on it?

## Exploration Strategy

Use the `explore` agent or glob/grep tools to:

1. **Find relevant source files:**
   ```
   glob pattern: **/*{{label}}*
   grep pattern: {{label}} (case insensitive)
   ```

2. **Scan directory structure:**
   - `src/` — main source code
   - `tests/` — test files
   - `docs/` — documentation

3. **Read key files:**
   - Main module entry points
   - Core classes/functions
   - Test files to understand expected behavior

## Output Format

After exploration, provide a brief summary:

```
## {{label}} Code Area Summary

**Main Files:**
- path/to/file1.py — description
- path/to/file2.py — description

**Key Abstractions:**
- ClassName — purpose
- function_name() — purpose

**Testing:**
- Test location: tests/path/
- Test patterns: description

**Dependencies:**
- Depends on: module1, module2
- Used by: module3, module4
```

## Important Notes

- This is a **read-only exploration** — do not modify any files
- Focus on breadth over depth — understand the layout, not every detail
- Keep your summary concise — this context will be used for future work items
- If the label doesn't correspond to obvious files, search for related concepts

## Time Budget

Spend at most 2-3 minutes on exploration. The goal is to prime the session with useful context, not to deeply understand every aspect of the code.
