# PokePoke Logging

## Overview

PokePoke now includes comprehensive file-based logging to capture all orchestrator actions and agent interactions. This makes it easy to review what happened during a run without needing to scroll through potentially very long console output.

## Log Structure

Each PokePoke run creates a unique directory with the following structure:

```
logs/
└── YYYYMMDD_HHMMSS_<uuid>/
    ├── orchestrator.log          # High-level orchestrator actions
    └── items/
        ├── item-id-1.log         # Agent output for first work item
        ├── item-id-2.log         # Agent output for second work item
        └── ...
```

### Run ID Format

Each run gets a unique ID in the format:
- `YYYYMMDD_HHMMSS_<short-uuid>`
- Example: `20260123_143052_a3b4c5d6`

The run ID is:
- **Displayed on exit** - Always shown at the end of the run
- **Timestamped** - The date and time when the run started
- **Unique** - Short UUID suffix prevents collisions

## Log Types

### 1. Orchestrator Log (`orchestrator.log`)

Contains high-level orchestrator actions **without agent output**. This gives you a bird's-eye view of what PokePoke did during the run.

**Contents:**
- Run initialization
- Work item selection
- Repository status checks
- Maintenance agent runs
- Error conditions
- Run summary

**Example:**
```
[2026-01-23 14:30:52] [INFO] PokePoke started in Interactive mode
[2026-01-23 14:30:52] [INFO] Repository: C:\Users\ameliapayne\PokePoke
[2026-01-23 14:30:55] [INFO] Selected item: PokePoke-6g1 - Add file logging feature
[2026-01-23 14:31:20] [INFO] Started processing work item: PokePoke-6g1 - Add file logging feature
[2026-01-23 14:45:10] [INFO] Completed work item with 3 agent requests - Status: SUCCESS
[2026-01-23 14:45:10] [INFO] Items completed this session: 1
[2026-01-23 14:45:15] [MAINTENANCE:janitor] Starting Janitor Agent
[2026-01-23 14:46:00] [MAINTENANCE:janitor] Janitor Agent completed successfully
```

### 2. Item Logs (`items/<item-id>.log`)

Contains **complete agent output** for each work item processed. This is the full, detailed log of everything the agent did, said, and produced.

**Contents:**
- Full prompt sent to agent
- Agent responses (streamed in real-time)
- Tool calls and results
- Agent thinking and reasoning
- Success/failure status
- Request count

**Example:**
```
[2026-01-23 14:31:20] [INFO] Invoking Copilot SDK for work item: PokePoke-6g1
[2026-01-23 14:31:20] [INFO] Title: Add file logging feature
[2026-01-23 14:31:20] [INFO] Max timeout: 120.0 minutes
================================================================
Full Prompt Being Sent:
================================================================
You are working on a beads work item...
================================================================

[AGENT] Processing request...
I'll add file logging to PokePoke. Let me start by creating the logging module...
[TOOL] → create_file
[TOOL] ✓ create_file
...
[AGENT] Turn complete (15234 chars total)

[2026-01-23 14:45:10] [INFO] Result: SUCCESS
================================================================
Summary
================================================================
Completed: 2026-01-23 14:45:10
Status: SUCCESS
Agent requests: 3
================================================================
```

## Finding Your Logs

### 1. Note the Run ID on Exit

At the end of every run, PokePoke displays:
```
📝 Run ID: 20260123_143052_a3b4c5d6
📁 Logs saved to: C:\Users\ameliapayne\PokePoke\logs\20260123_143052_a3b4c5d6
```

### 2. Browse the Logs Directory

```powershell
# List all runs
ls logs/

# Open a specific run's orchestrator log
cat logs/20260123_143052_a3b4c5d6/orchestrator.log

# Open a specific item log
cat logs/20260123_143052_a3b4c5d6/items/PokePoke-6g1.log

# Open the most recent run
$latest = Get-ChildItem logs/ | Sort-Object LastWriteTime -Descending | Select-Object -First 1
cat "$latest\orchestrator.log"
```

### 3. Use Your Favorite Editor

```powershell
# Open in VS Code
code logs/20260123_143052_a3b4c5d6

# Open in Notepad
notepad logs/20260123_143052_a3b4c5d6/orchestrator.log
```

## When to Use Which Log

### Use Orchestrator Log When:
- ✅ Reviewing overall run flow
- ✅ Checking which items were processed
- ✅ Seeing when maintenance agents ran
- ✅ Investigating orchestrator-level errors
- ✅ Getting quick run statistics

### Use Item Logs When:
- ✅ Debugging agent behavior for a specific work item
- ✅ Reviewing what tools the agent used
- ✅ Understanding why an item succeeded or failed
- ✅ Seeing the full agent reasoning and output
- ✅ Analyzing agent performance

## Log Retention

Logs are stored in the `logs/` directory and are:
- **Not committed to git** - Logs are in `.gitignore`
- **Not automatically cleaned up** - You manage retention
- **Not size-limited** - Each run creates a new directory

**Cleanup:**
```powershell
# Remove all logs
rm -r logs/

# Remove logs older than 7 days
Get-ChildItem logs/ | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-7) } | Remove-Item -Recurse

# Keep only the 10 most recent runs
Get-ChildItem logs/ | Sort-Object LastWriteTime -Descending | Select-Object -Skip 10 | Remove-Item -Recurse
```

## Technical Details

### Architecture

The logging system consists of:
- `RunLogger` - Manages run-level logging
- `ItemLogger` - Manages per-item logging
- Logging integrated into orchestrator and SDK

### Console vs. File Logging

- **Console** - Real-time output, scrollable, color-coded
- **File** - Persistent, searchable, no color codes

Both receive the same content - file logs are a persistent copy of what appears on the console.

### Thread Safety

- All logging is synchronous (no concurrent writes)
- File handles are opened/closed for each write (no locking issues)
- Safe for single-orchestrator use (not designed for parallel runs)

## Future Enhancements

Potential improvements:
- Log rotation by size/age
- Compressed archive storage
- Log search/query CLI
- Structured JSON logs for machine parsing
- Log aggregation across multiple runs
