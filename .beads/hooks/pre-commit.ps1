#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Git pre-commit hook for PokePoke Python project
    
.DESCRIPTION
    Runs the following checks before allowing a commit, ordered cheapest-first
    so fast-fail catches obvious issues before expensive pytest/coverage runs:
    1. Integrity check (verifies quality scripts haven't been tampered with)
    2. File length check (trivial stat) [fast]
    3. Skipped tests check (grep) [fast]
    4. Test safety check (grep) [fast]
    5. Ruff lint check (syntax + style) [fast]
    6. Pokepoke boot check (import) [fast]
    7. Code quality check (mypy type checking) [medium]
    8. Test coverage check (modified files must have 80%+ coverage) [slow - runs pytest]
    9. Desktop ESLint check [if applicable]
    10. Desktop build check [if applicable]

.NOTES
    ⚠️  CRITICAL: This file is protected by CODEOWNERS
    Any modifications require @ameliapayne approval
    
.EXAMPLE
    # Normal commit (runs all checks)
    git commit -m "fix: resolve issue"
#>

$ErrorActionPreference = "Stop"

# Get repository root
$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}

# Ensure CWD is the repo/worktree root for all child scripts.
# In git worktrees, CWD should already be the worktree root,
# but we set it explicitly for robustness.
Set-Location $repoRoot

Write-Host "Pre-commit checks:" -ForegroundColor Cyan

$hooksDir = Join-Path $repoRoot ".githooks"
$overallStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

# Timeout caps — defense-in-depth against hanging tests/checks
$PerCheckTimeoutSeconds = 720    # 12 min per individual check
$OverallTimeoutMinutes  = 15     # 15 min for entire pre-commit hook
$TimeoutDiagnostics = @"
Tests are likely hanging. Check for:
  - Tests using real subprocess/git calls without mocking
  - Tests waiting for stdin input
  - Select-Object -First/-Last piping
Run pytest with --timeout=30 to find the hanging test.
"@

# Run standalone integrity verification
Write-Host "  • Running standalone verification... " -NoNewline -ForegroundColor Gray
$verifyScript = Join-Path $hooksDir "verify-integrity.ps1"
& $verifyScript *>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗" -ForegroundColor Red
    Write-Host ""
    & $verifyScript  # Run again with output for user to see
    exit 1
}
Write-Host "✓" -ForegroundColor Green

$allPassed = $true
$passed = @()
$failed = @()

# Unified pipeline ordered cheapest-first (fast-fail: first failure exits).
# Cheap checks (grep/stat) run before expensive ones (mypy, pytest/coverage).
# Each entry can specify:
#   - Isolated: $true  → run via Start-Process with per-check timeout (for checks that may hang)
#   - Interpreter       → use a specific interpreter (e.g. "python") instead of pwsh
$checks = @(
    # --- Fast checks (grep, stat, import) ---
    @{ Name = "File Length";    Script = "check-file-length.ps1" }
    @{ Name = "Skipped Tests";  Script = "check-skipped-tests.ps1" }
    @{ Name = "Test Safety";    Script = "check-test-safety.ps1" }
    @{ Name = "Ruff Lint";      Script = "check-ruff.ps1" }
    @{ Name = "Pokepoke Boot";  Script = "check-pokepoke-import.ps1" }
    # --- Medium checks ---
    @{ Name = "Code Quality";   Script = "check-code-quality.ps1"; Isolated = $true }
    # --- Slow checks (runs full pytest suite) ---
    @{ Name = "Test Coverage";  Script = "check-coverage.py"; Isolated = $true; Interpreter = "python" }
    # --- Desktop checks (only run when desktop files are staged) ---
    @{ Name = "Desktop ESLint"; Script = "check-desktop-lint.ps1" }
    @{ Name = "Desktop Build";  Script = "check-build.ps1" }
)

foreach ($check in $checks) {
    # Overall timeout guard
    if ($overallStopwatch.Elapsed.TotalMinutes -ge $OverallTimeoutMinutes) {
        Write-Host ""
        Write-Host "⏰ Pre-commit timed out after $([math]::Round($overallStopwatch.Elapsed.TotalMinutes, 1)) minutes." -ForegroundColor Red
        Write-Host $TimeoutDiagnostics -ForegroundColor Yellow
        exit 1
    }

    if ($check.Isolated) {
        # Run via Start-Process with hard timeout (for checks that may hang)
        Write-Host "  • $($check.Name)... " -ForegroundColor Gray
        $checkStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

        try {
            $checkScript = Join-Path $hooksDir $check.Script
            if ($check.Interpreter) {
                $proc = Start-Process -FilePath $check.Interpreter -ArgumentList $checkScript `
                    -NoNewWindow -PassThru -WorkingDirectory $repoRoot
            } else {
                $proc = Start-Process -FilePath "pwsh" `
                    -ArgumentList "-NoProfile", "-NonInteractive", "-File", $checkScript `
                    -NoNewWindow -PassThru -WorkingDirectory $repoRoot
            }

            $exited = $proc.WaitForExit($PerCheckTimeoutSeconds * 1000)
            $checkStopwatch.Stop()

            if (-not $exited) {
                try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
                $elapsed = [math]::Round($checkStopwatch.Elapsed.TotalMinutes, 1)
                Write-Host "    ⏱ $($check.Name): TIMED OUT after ${elapsed} min" -ForegroundColor Red
                Write-Host ""
                Write-Host "⏰ Pre-commit timed out after ${elapsed} minutes." -ForegroundColor Red
                Write-Host $TimeoutDiagnostics -ForegroundColor Yellow
                exit 1
            }

            if ($proc.ExitCode -eq 0) {
                Write-Host "    ⏱ $($check.Name): $([math]::Round($checkStopwatch.Elapsed.TotalSeconds, 1))s" -ForegroundColor DarkGray
                $passed += $check.Name
            }
            else {
                Write-Host "    ⏱ $($check.Name): $([math]::Round($checkStopwatch.Elapsed.TotalSeconds, 1))s" -ForegroundColor DarkGray
                $failed += $check.Name
                $allPassed = $false
                Write-Host "  ⚡ Check failed — skipping remaining checks" -ForegroundColor Yellow
                break
            }
        }
        catch {
            $checkStopwatch.Stop()
            Write-Host "    ⏱ $($check.Name): $([math]::Round($checkStopwatch.Elapsed.TotalSeconds, 1))s" -ForegroundColor DarkGray
            Write-Host "Error: $_" -ForegroundColor Red
            $failed += $check.Name
            $allPassed = $false
            Write-Host "  ⚡ Check failed — skipping remaining checks" -ForegroundColor Yellow
            break
        }
    }
    else {
        # Run inline (fast checks that won't hang)
        Write-Host "  • $($check.Name)... " -NoNewline -ForegroundColor Gray
        $checkStopwatch = [System.Diagnostics.Stopwatch]::StartNew()

        try {
            $checkScript = Join-Path $hooksDir $check.Script
            $output = & $checkScript *>&1 | Out-String
            $checkStopwatch.Stop()

            if ($LASTEXITCODE -eq 0) {
                Write-Host "✓" -ForegroundColor Green
                $passed += $check.Name
            }
            else {
                Write-Host "✗" -ForegroundColor Red
                $failed += $check.Name
                $allPassed = $false
                if ($output.Trim()) {
                    Write-Host ""
                    Write-Host $output.Trim()
                    Write-Host ""
                }
                Write-Host "  ⚡ Check failed — skipping remaining checks" -ForegroundColor Yellow
                break
            }
        }
        catch {
            $checkStopwatch.Stop()
            Write-Host "✗" -ForegroundColor Red
            Write-Host "Error: $_" -ForegroundColor Red
            $failed += $check.Name
            $allPassed = $false
            Write-Host "  ⚡ Check failed — skipping remaining checks" -ForegroundColor Yellow
            break
        }
    }
}

Write-Host ""

$overallStopwatch.Stop()
$totalSeconds = [math]::Round($overallStopwatch.Elapsed.TotalSeconds, 1)

if ($allPassed) {
    Write-Host "✅ All checks passed ($($totalSeconds)s)" -ForegroundColor Green
    exit 0
}
else {
    Write-Host "❌ $($failed.Count) check(s) failed: $($failed -join ', ') ($($totalSeconds)s)" -ForegroundColor Red
    exit 1
}
