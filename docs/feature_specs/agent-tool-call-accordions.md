# Agent tool call accordions

**Status:** Implemented  
**Version:** 2026-02-13  
**UI Surface:** Desktop log panels

## Overview

The desktop agent log panel collapses tool call output into expandable accordion rows, surfacing only the tool name and a short result summary by default.

## Purpose

Reduce log noise from verbose tool outputs while keeping tool usage visible at a glance.

## User-Facing Behavior

- Agent log entries that represent tool calls are rendered as collapsed accordions.
- The summary line shows the tool name and a truncated result snippet when available.
- Clicking the accordion expands to show the raw tool call and result lines.
- Non-tool log entries render as before.

## Input Parameters

None. The UI derives accordion state from the existing log line format.

## Output Format

When collapsed, users see a single summary line:

```
🔧 <tool-name> — ✅ <result summary>
```

When expanded, users see the full tool call and result lines underneath the summary.

## Examples

**Collapsed summary:**
```
🔧 rg — ✅ 3 matches in 1 file…
```

**Expanded details:**
```
🔧 rg({"pattern":"tool call","path":"src"})
✅ Result: 3 matches in 1 file (src/log.ts)
```

## Error Handling

If a tool result has not arrived yet, the accordion renders only the tool name without a result summary.

## Implementation Details

- **Component:** `desktop/src/components/LogPanel.tsx`
- **Styles:** `desktop/src/App.css`

## Testing

- `python -m pytest`
- `npm run lint` (from `desktop/`)
- `npm run build` (from `desktop/`)

## Changelog

- **2026-02-13:** Initial implementation.
