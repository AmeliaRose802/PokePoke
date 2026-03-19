# PokePoke

Autonomous workflow orchestrator that integrates the Beads issue tracker with the GitHub Copilot SDK for automated development.

## Installation

### Desktop installer (recommended)

The desktop installer is the easiest way to get PokePoke running on Windows.

**Prerequisites:**

- Windows 10 or later
- [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) (the installer will attempt to install this automatically if missing)

**Steps:**

1. Build the installer locally by following [packaging/installer/README.md](packaging/installer/README.md).
2. Run the installer. If prompted by SmartScreen, click **More info** → **Run anyway**.
3. Choose an install location (defaults to `C:\Program Files\PokePoke`).
4. The installer creates Start Menu and Desktop shortcuts automatically.

Pre-built installers may be published on the [Releases](https://github.com/AmeliaRose802/PokePoke/releases) page in the future. If available, download the latest `PokePokeInstaller-<version>.exe` instead of building locally.

**What the installer sets up:**

- The PokePoke desktop application (`PokePoke.exe`)
- Start Menu shortcuts (app + uninstall)
- Desktop shortcut
- WebView2 Runtime (if not already present)
- Add/Remove Programs entry for easy uninstallation

To uninstall, use **Add/Remove Programs** in Windows Settings or run the uninstaller from the Start Menu.

### Install from source (for development)

```bash
pip install -e .
```

Requires Python 3.12 or later.

## Usage

```bash
# Interactive mode (manual work item selection)
python -m pokepoke.orchestrator --interactive

# Autonomous mode (automatic selection, no prompts)
python -m pokepoke.orchestrator --autonomous

# Continuous mode (process multiple items in a loop)
python -m pokepoke.orchestrator --interactive --continuous
python -m pokepoke.orchestrator --autonomous --continuous
```

## AI backend configuration

PokePoke supports pluggable AI backends. Configure `.pokepoke/config.yaml`:

```yaml
ai_backend:
  provider: copilot        # or claude-code
  copilot_cli_path: copilot.cmd
  claude_code_cli_path: claude
```

The Copilot adapter remains the default; setting `provider: claude-code` switches to the Claude Code CLI adapter. Worktrees and orchestrator workflows automatically honor the selected provider.

## Task tracker backend configuration

PokePoke uses the [beads](https://github.com/steveyegge/beads) issue tracker for work-item management. Two CLI backends are supported:

| Backend | Binary | Description | Sync strategy |
|---------|--------|-------------|---------------|
| **bd** (default) | `bd` | Python implementation | Daemon-based auto-sync |
| **br** | `br` | Rust implementation | Explicit sync (manual `br sync` + git push) |

Both backends share the same command-line interface and produce identical JSON output, so all PokePoke orchestration works identically with either one.

### Selecting a backend

The active backend defaults to `bd`. To switch to `br`, call `set_active_backend()` at startup:

```python
from pokepoke.beads.beads_query import set_active_backend, BR_CONFIG

set_active_backend(BR_CONFIG)  # Switch to the Rust backend
```

The backend selection also configures the appropriate sync strategy automatically:
- **bd** → `DaemonSync` (background daemon commits to the `beads-sync` branch)
- **br** → `ExplicitSync` (requires explicit `br sync` calls and git operations)

### Adding a new backend

To add a new beads CLI backend:

1. Define a new `CLIBackendConfig` in `src/pokepoke/beads/beads_query.py`:
   ```python
   NEW_CONFIG = CLIBackendConfig(binary="new-binary", default_timeout=30)
   ```
2. If the new backend has different sync behaviour, create a `SyncStrategy` subclass in `src/pokepoke/beads/sync_strategy.py`.
3. Update `set_active_backend()` to wire up the correct sync strategy for the new backend.
4. All existing callers use `_run_bd()`, which delegates to `_run_cli()` with the active backend — no further changes needed.

## Pre-flight Health Checks

PokePoke includes a comprehensive pre-flight health check system that runs before each work batch to prevent submission to broken environments. This system addresses issues where broken environments (stale locks, dirty git state) caused silent failures with 0 agent requests.

### Health Checks Performed

1. **Git Status Verification**: Ensures the repository is in a clean state with no uncommitted changes
2. **Worktree Creation Test**: Verifies that worktrees can be created successfully  
3. **Lock Availability Check**: Checks that required locks are available and identifies stale locks
4. **Disk Space Check**: Ensures sufficient disk space is available for worktree operations
5. **Repository Integrity Check**: Detects orphaned worktrees and other integrity issues

### Automatic Self-Repair

When health check failures are detected, PokePoke can automatically attempt repairs:

- **Clear Stale Locks**: Removes locks where the holder process is no longer running
- **Reset Dirty Git State**: Auto-commits or stashes uncommitted changes
- **Prune Orphan Worktrees**: Cleans up worktree directories that are no longer registered
- **General Cleanup**: Removes temporary files and corrupted lock files

### Error Classification

Health check errors are classified to determine the appropriate response:

- **Environmental Errors**: Stop all work (e.g., insufficient disk space, critical git issues)
- **Item-Specific Errors**: Skip the current item, continue with others
- **Recoverable Errors**: Attempt automatic self-repair
- **Critical Errors**: Immediate graceful shutdown with diagnostics

### Configuration

Configure pre-flight health checks in `.pokepoke/config.yaml`:

```yaml
preflight_health:
  enabled: true                     # Enable/disable health checks
  min_disk_space_gb: 1.0           # Minimum free disk space required
  lock_timeout_seconds: 30.0       # Timeout for lock operations
  worktree_test_timeout: 60.0      # Timeout for worktree creation test
  max_orphan_worktrees: 10         # Maximum orphaned worktrees before error
  git_operation_timeout: 30.0      # Timeout for git operations
  enable_self_repair: true         # Enable automatic self-repair
  max_repair_attempts: 3           # Maximum self-repair attempts per issue
  fail_on_environmental_errors: true    # Stop on environmental issues
  fail_on_critical_errors: true         # Stop on critical issues
  graceful_shutdown_on_failure: true    # Shutdown gracefully vs exit immediately
```

### Diagnostic Output

When health checks fail, detailed diagnostics are provided:

```
❌ Pre-flight health checks failed (3 error(s))
   • git_status_check: Repository has uncommitted changes: 2 files
   • disk_space_check: Insufficient disk space: 0.5GB free, 1.0GB required
   • repository_integrity_check: Too many orphaned worktrees: 12 (max: 10)

✅ Self-repair completed successfully
✅ Pre-flight health checks passed after self-repair
```

### Integration with Orchestrator

Health checks run automatically in both sequential and parallel orchestrator modes:

1. **Before Work Batch**: Checks run before fetching work from beads
2. **Self-Repair**: Automatic repair attempts for recoverable issues
3. **Error Handling**: Appropriate response based on error severity classification
4. **Graceful Shutdown**: Clean shutdown with diagnostics on unrecoverable failures

The system prevents the scenario where broken environments accept work items but fail silently, ensuring reliable operation and early problem detection.
