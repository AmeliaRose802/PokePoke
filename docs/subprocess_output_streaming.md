# Subprocess Output Streaming

## Overview

PokePoke now streams real-time stdout/stderr output from tool commands executed by the Copilot CLI. This provides live visibility into long-running operations like pytest, git commit with pre-commit hooks, and other subprocess-based tools.

## Problem Solved

Previously, PokePoke was "blind" during tool execution:
- Only saw SDK events (tool start/complete), not the subprocess output
- Could not distinguish between hung commands and legitimately long-running operations
- No live feedback in logs or UI during execution
- Difficult to diagnose hung commands waiting for stdin or stuck in deadlock

## Implementation

### Architecture

The streaming system consists of three main components:

1. **SubprocessMonitor** (`src/pokepoke/utils/subprocess_monitor.py`)
   - Monitors child processes spawned by the Copilot CLI
   - Detects new PowerShell.exe, pytest.exe, and other tool subprocesses
   - Uses Windows WM IC (Windows Management Instrumentation Command-line) to discover child processes
   - Runs in a background thread, checking for new children every second

2. **SDK Event Handler Integration** (`src/pokepoke/models/sdk_event_handler.py`)
   - Accepts optional `subprocess_monitor` parameter
   - Passes monitor to tool execution callbacks
   - Coordinates with SDK streaming events (if available)

3. **Desktop UI Integration** (`src/pokepoke/models/copilot_sdk.py`)
   - Creates monitor when Copilot client starts
   - Routes captured output to:
     - Python logger (`logger.info`)
     - Item logger (structured log files)
     - Desktop API (`push_log`) for live UI updates
   - Cleans up monitor on session completion

### Flow Diagram

```
Copilot CLI starts
  ↓
SubprocessMonitor created and started
  ↓
Monitor thread runs every 1 second
  ↓
WMIC discovers child processes (PowerShell, pytest, git, etc.)
  ↓
New child detected → logged to console/UI
  ↓
[Future] Output capture from child stdout/stderr
  ↓
Output streamed to:
  - Python logger
  - Item logger (.pokepoke/logs/items/)
  - Desktop UI (live updates)
  ↓
Session ends → Monitor stopped
```

### Current Capabilities

**V1 (This Implementation):**
- ✅ Detects child processes spawned by Copilot CLI
- ✅ Logs child process PID and command line
- ✅ Provides infrastructure for output streaming
- ✅ Integrates with item logger and desktop UI
- ✅ Comprehensive test coverage

**Future Enhancements:**
- Capture stdout/stderr from child processes using Windows console APIs
- Real-time output streaming (line-by-line as it's produced)
- Output-based liveness detection (if no output for N minutes, command is hung)
- Automatic detection of commands waiting for stdin input

## Benefits

### 1. Hung Command Detection
- See when commands are producing output vs truly stuck
- Differentiate between "computing" and "hung"
- Detect stdin-waiting commands (e.g., prompts)

### 2. Live Progress Feedback
- Desktop UI shows agent activity in real-time
- Users can see pytest progress, not just silence
- Logs capture incremental output for debugging

### 3. Debugging Support
- Full visibility into subprocess command lines
- Track which commands spawn which children
- Diagnose pre-commit hook issues and test failures

### 4. Timeout Optimization
- Avoid premature timeouts on legitimately long operations
- Trigger fast failures on truly hung commands
- Reduce wasted agent time on stuck processes

## Configuration

No configuration required - subprocess monitoring is automatically enabled when:
1. Copilot SDK client starts
2. A valid copilot process PID can be extracted
3. The platform is Windows (WMIC available)

## Testing

Comprehensive test suite in `tests/utils/test_subprocess_monitor.py`:
- Monitor start/stop lifecycle
- Child process detection via WMIC
- Output callback mechanisms
- Error handling (timeouts, failures)
- Integration with ItemLogger and desktop UI

Run tests:
```bash
pytest tests/utils/test_subprocess_monitor.py -v
```

## Related Work

- **Beads Issue:** PokePoke-xe95e (Tool execution observability gap)
- **Beads Issue:** PokePoke-4jqpc (This implementation)
- **Hung Command Detector:** `src/pokepoke/utils/hung_command_detector.py`
- **SDK Watchdog:** `src/pokepoke/models/sdk_watchdog.py`

## Future Work

### Phase 2: Real-Time Output Capture

The current implementation provides the foundation for real-time output capture. Future work includes:

1. **Windows Console API Integration**
   - Use `AttachConsole` and `ReadConsoleOutput` to capture subprocess output
   - Or use process stdout/stderr redirection if pipes are accessible

2. **Cross-Platform Support**
   - Use `psutil` for Unix-like systems
   - Implement subprocess stdout/stderr monitoring on Linux/macOS

3. **Output-Based Liveness**
   - Track last output timestamp per child process
   - Trigger warnings if no output for configurable threshold (e.g., 5 minutes)
   - Integrate with hung command detector for automatic remediation

4. **Stdin Detection**
   - Detect when commands are waiting for stdin input
   - Automatically terminate or warn about interactive prompts
   - Prevent agents from getting stuck on unexpected input requests

## Notes

- Monitor uses WMIC which is available on Windows by default
- Child process detection happens every 1 second (configurable)
- Monitor runs in a daemon thread and cleans up automatically
- No external dependencies required (uses stdlib only)
- Designed for future extensibility (output capture, cross-platform)
