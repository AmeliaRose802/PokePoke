<#
.SYNOPSIS
    Watchdog script that monitors PokePoke, debugs failures with Copilot CLI, and restarts.

.DESCRIPTION
    Runs PokePoke in a loop. When PokePoke exits:
    1. Finds the latest run log directory
    2. Invokes Copilot CLI to analyze the logs and diagnose the failure
    3. Resets stale in-progress items to open/unassigned
    4. Cleans up orphaned worktrees
    5. Restarts PokePoke

    Blocks while PokePoke is running (tails the orchestrator log).

.PARAMETER MaxAgents
    Number of parallel agents. Default: 8

.PARAMETER MaxRestarts
    Maximum number of restart cycles. Default: unlimited (0)

.PARAMETER SkipDebug
    Skip the Copilot CLI debug step after exit.

.EXAMPLE
    .\scripts\Watch-PokePoke.ps1
    .\scripts\Watch-PokePoke.ps1 -MaxAgents 4 -MaxRestarts 5
#>
param(
    [int]$MaxAgents = 8,
    [int]$MaxRestarts = 0,
    [switch]$SkipDebug
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

# Activate venv if present
$venvActivate = Join-Path $repoRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) { & $venvActivate }

$restartCount = 0

function Get-LatestRunDir {
    $logsDir = Join-Path $repoRoot ".pokepoke\logs"
    if (-not (Test-Path $logsDir)) { return $null }
    Get-ChildItem $logsDir -Directory |
        Sort-Object Name -Descending |
        Select-Object -First 1 |
        Select-Object -ExpandProperty FullName
}

function Reset-StaleItems {
    Write-Host "`n--- Resetting stale in-progress items ---" -ForegroundColor Cyan
    try {
        $raw = & bd list --status in_progress --json 2>&1
        $items = $raw | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($items -and $items.Count -gt 0) {
            foreach ($item in $items) {
                & bd update $item.id --status open --unassign --json 2>&1 | Out-Null
                Write-Host "  Reset: $($item.id) - $($item.title.Substring(0, [Math]::Min(60, $item.title.Length)))"
            }
            Write-Host "  Reset $($items.Count) item(s)" -ForegroundColor Green
        } else {
            Write-Host "  No stale items found" -ForegroundColor Gray
        }
    } catch {
        Write-Host "  Warning: Failed to reset items: $_" -ForegroundColor Yellow
    }
}

function Remove-OrphanedWorktrees {
    Write-Host "`n--- Cleaning orphaned worktrees ---" -ForegroundColor Cyan
    try {
        & git worktree prune 2>&1 | Out-Null
        $worktrees = & git worktree list --porcelain 2>&1
        $taskWorktrees = ($worktrees | Select-String "^worktree .+task-").Count
        if ($taskWorktrees -gt 5) {
            $wtList = & git worktree list 2>&1
            foreach ($line in $wtList) {
                if ($line -match "^(.+?)\s+\w+\s+\[task/") {
                    $wtPath = $matches[1].Trim()
                    if ($wtPath -ne $repoRoot) {
                        & git worktree remove $wtPath --force 2>&1 | Out-Null
                    }
                }
            }
            & git worktree prune 2>&1 | Out-Null
            Write-Host "  Cleaned up task worktrees" -ForegroundColor Green
        } else {
            Write-Host "  Worktrees OK ($taskWorktrees task worktrees)" -ForegroundColor Gray
        }
    } catch {
        Write-Host "  Warning: Worktree cleanup failed: $_" -ForegroundColor Yellow
    }
}

function Remove-StaleLocks {
    Write-Host "`n--- Clearing stale locks ---" -ForegroundColor Cyan
    $lockDir = Join-Path $repoRoot ".pokepoke\locks"
    if (Test-Path $lockDir) {
        Get-ChildItem $lockDir -Filter "*.lock" -File | ForEach-Object {
            Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
            Write-Host "  Removed lock: $($_.Name)"
        }
    }
    # Git index lock
    $gitLock = Join-Path $repoRoot ".git\index.lock"
    if (Test-Path $gitLock) {
        Remove-Item $gitLock -Force -ErrorAction SilentlyContinue
        Write-Host "  Removed .git/index.lock"
    }
    Write-Host "  Locks cleared" -ForegroundColor Green
}

function Invoke-CopilotDebug {
    param([string]$RunDir)

    Write-Host "`n--- Invoking Copilot CLI to debug run ---" -ForegroundColor Cyan
    $orchLog = Join-Path $RunDir "orchestrator.log"
    if (-not (Test-Path $orchLog)) {
        Write-Host "  No orchestrator.log found in $RunDir" -ForegroundColor Yellow
        return
    }

    $logContent = Get-Content $orchLog -Tail 100 -ErrorAction SilentlyContinue
    $lastLines = ($logContent | Select-Object -Last 80) -join "`n"

    # Get error lines
    $errorLines = Select-String -Path $orchLog -Pattern "\[ERROR\]|\[CRITICAL\]|exception|circuit.breaker|lock.*could not" -ErrorAction SilentlyContinue
    $errorSummary = if ($errorLines) {
        ($errorLines | ForEach-Object { $_.Line } | Select-Object -Last 20) -join "`n"
    } else {
        "No explicit errors found in log."
    }

    # Get stats if available
    $statsFile = Join-Path $RunDir "stats.json"
    $statsInfo = if (Test-Path $statsFile) {
        Get-Content $statsFile -Raw -ErrorAction SilentlyContinue
    } else {
        "No stats.json available."
    }

    $prompt = @"
You are analyzing a PokePoke orchestrator run that just exited. Your job is to:
1. Diagnose WHY the run ended (circuit breaker? merge conflict? lock contention? crash?)
2. Identify any items that failed repeatedly and WHY
3. Check if there are fixable issues (dirty repo, stale locks, merge conflicts)
4. If you find code bugs causing the failure, fix them and commit
5. If the repo has uncommitted changes or merge conflicts, resolve them

Run directory: $RunDir

LAST 80 LINES OF ORCHESTRATOR LOG:
$lastLines

ERROR LINES:
$errorSummary

STATS:
$statsInfo

INSTRUCTIONS:
- Check git status for merge conflicts (UU files) and resolve them
- Check for ruff lint errors in uncommitted files and fix them
- If the main repo is dirty, try to commit or discard changes appropriately
- Do NOT modify .githooks/ files
- Do NOT create summary documents
- Be brief in your analysis
- If you fix something, commit it with a descriptive message
- After fixing, report what you did so the watchdog can restart PokePoke
"@

    Write-Host "  Prompt length: $($prompt.Length) chars" -ForegroundColor Gray
    Write-Host "  Running copilot.cmd analysis..." -ForegroundColor Yellow

    try {
        & copilot.cmd -p $prompt --allow-all-tools --no-ask-user --autopilot 2>&1 |
            ForEach-Object { Write-Host "  [copilot] $_" }
        Write-Host "  Copilot debug completed" -ForegroundColor Green
    } catch {
        Write-Host "  Warning: Copilot debug failed: $_" -ForegroundColor Yellow
    }
}

function Start-PokePoke {
    Write-Host "`n=== Starting PokePoke (agents=$MaxAgents) ===" -ForegroundColor Green
    Write-Host "  Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

    $proc = Start-Process -FilePath "python" `
        -ArgumentList "-m", "pokepoke", "--autonomous", "--continuous", "--max-agents", $MaxAgents `
        -WorkingDirectory $repoRoot `
        -PassThru `
        -NoNewWindow

    Write-Host "  PID: $($proc.Id)"
    return $proc
}

function Wait-ForPokePoke {
    param([System.Diagnostics.Process]$Process)

    Write-Host "`n--- Monitoring PokePoke (PID $($Process.Id)) ---" -ForegroundColor Cyan

    # Wait for the log file to appear
    Start-Sleep -Seconds 10
    $runDir = Get-LatestRunDir
    $orchLog = if ($runDir) { Join-Path $runDir "orchestrator.log" } else { $null }

    $lastLineCount = 0
    $staleSince = $null
    $staleThresholdMinutes = 15

    while (-not $Process.HasExited) {
        Start-Sleep -Seconds 30

        # Refresh log path in case run ID changed
        $currentRunDir = Get-LatestRunDir
        if ($currentRunDir -ne $runDir) {
            $runDir = $currentRunDir
            $orchLog = Join-Path $runDir "orchestrator.log"
            $lastLineCount = 0
        }

        if ($orchLog -and (Test-Path $orchLog)) {
            $lineCount = (Get-Content $orchLog | Measure-Object).Count
            $delta = $lineCount - $lastLineCount

            # Show latest completion info
            $completedLine = Select-String -Path $orchLog -Pattern "Items completed" -ErrorAction SilentlyContinue |
                Select-Object -Last 1
            $errorCount = (Select-String -Path $orchLog -Pattern "\[ERROR\]" -ErrorAction SilentlyContinue |
                Measure-Object).Count
            $activeMatch = Select-String -Path $orchLog -Pattern "Lifecycle: active=(\d+)" -ErrorAction SilentlyContinue |
                Select-Object -Last 1

            $completed = if ($completedLine) { ($completedLine.Line -split "session: ")[1] } else { "0" }
            $active = if ($activeMatch -and $activeMatch.Line -match "active=(\d+)") { $matches[1] } else { "?" }

            $ts = Get-Date -Format "HH:mm:ss"
            Write-Host "  [$ts] Log: $lineCount lines (+$delta) | Completed: $completed | Active: $active | Errors: $errorCount" -ForegroundColor Gray

            if ($delta -eq 0) {
                if ($null -eq $staleSince) { $staleSince = Get-Date }
                $staleMinutes = [math]::Round(((Get-Date) - $staleSince).TotalMinutes, 1)
                if ($staleMinutes -gt $staleThresholdMinutes) {
                    Write-Host "  WARNING: Log stale for ${staleMinutes}m" -ForegroundColor Yellow
                }
            } else {
                $staleSince = $null
            }

            $lastLineCount = $lineCount
        }
    }

    $exitCode = $Process.ExitCode
    Write-Host "`n  PokePoke exited with code $exitCode at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor $(if ($exitCode -eq 0) { "Green" } else { "Red" })
    return $exitCode
}

# ══════════════════════════════════════════════════════════════════════════════
# Main watchdog loop
# ══════════════════════════════════════════════════════════════════════════════

Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║  PokePoke Watchdog - Monitor & Restart      ║" -ForegroundColor Magenta
Write-Host "║  MaxAgents: $MaxAgents | MaxRestarts: $(if($MaxRestarts -eq 0){'unlimited'}else{$MaxRestarts})        ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Magenta

while ($true) {
    $restartCount++
    if ($MaxRestarts -gt 0 -and $restartCount -gt $MaxRestarts) {
        Write-Host "`nMax restarts ($MaxRestarts) reached. Exiting watchdog." -ForegroundColor Yellow
        break
    }

    Write-Host "`n════════════════════════════════════════" -ForegroundColor Magenta
    Write-Host "  Cycle $restartCount $(if($MaxRestarts -gt 0){"/ $MaxRestarts"}) - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Magenta
    Write-Host "════════════════════════════════════════" -ForegroundColor Magenta

    # Pre-start cleanup
    Reset-StaleItems
    Remove-StaleLocks
    Remove-OrphanedWorktrees

    # Ensure repo is clean
    $dirty = & git status --short 2>&1
    if ($dirty) {
        Write-Host "`n--- Repo has uncommitted changes ---" -ForegroundColor Yellow
        $dirty | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }

        # Check for merge conflicts
        $conflicts = $dirty | Where-Object { $_ -match "^UU |^AA |^DD " }
        if ($conflicts) {
            Write-Host "  Merge conflicts detected - aborting merge" -ForegroundColor Red
            & git merge --abort 2>&1 | Out-Null
            & git checkout -- . 2>&1 | Out-Null
        }
    }

    # Start PokePoke
    $proc = Start-PokePoke

    # Block while running
    $exitCode = Wait-ForPokePoke -Process $proc

    # Post-exit analysis
    $runDir = Get-LatestRunDir
    Write-Host "`n  Run directory: $runDir" -ForegroundColor Gray

    if (-not $SkipDebug) {
        Invoke-CopilotDebug -RunDir $runDir
    }

    # Brief cooldown before restart
    Write-Host "`n  Restarting in 30 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 30
}

Write-Host "`nWatchdog exited." -ForegroundColor Magenta
