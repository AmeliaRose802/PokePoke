#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Git pre-commit hook for PokePoke Python project
    
.DESCRIPTION
    Runs the following checks before allowing a commit:
    1. Integrity check (verifies quality scripts haven't been tampered with)
    2. Build check (Python syntax validation) [sequential]
    3. Code quality check (mypy type checking) [sequential, after build]
    4. Test coverage check (modified files must have 80%+ coverage) [sequential, after mypy]
    5. Skipped tests check (no skipped pytest tests) [parallel]
    6. Ruff lint check [parallel]
    7. File length check [parallel]
    8. Desktop lint check [parallel]

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

# Detect staged file types to skip irrelevant checks.
# Avoids expensive Start-Job overhead on Windows when no relevant files exist.
$stagedPaths = @(git diff --cached --name-only --diff-filter=ACM 2>$null)
$hasStagedPython = ($stagedPaths | Where-Object {
    $_ -match '\.py$' -and $_ -notmatch '(venv|\.venv|__pycache__|dist|build|worktrees)'
}).Count -gt 0

# Checks that don't depend on build artifacts - can run in parallel
$staticChecks = @(
    @{ Name = "Pokepoke Boot"; Script = "check-pokepoke-import.ps1" }
    @{ Name = "Skipped Tests"; Script = "check-skipped-tests.ps1" }
    @{ Name = "File Length"; Script = "check-file-length.ps1" }
    @{ Name = "Desktop ESLint"; Script = "check-desktop-lint.ps1" }
    # Desktop TypeScript check removed: check-build.ps1 already runs
    # tsc -b via "npm run build" (tsc -b && vite build), so running
    # check-desktop.ps1 separately duplicates TS error output.
)

if ($hasStagedPython) {
    $staticChecks += @{ Name = "Ruff Lint"; Script = "check-ruff.ps1" }
} else {
    Write-Host "  • Ruff Lint... " -NoNewline -ForegroundColor Gray
    Write-Host "skip (no Python files staged)" -ForegroundColor DarkGray
    $passed += "Ruff Lint"
}

# Checks that need build artifacts or must run in sequence: build -> mypy -> coverage
# If build or mypy fails, coverage is skipped (early exit on first failure)
$buildDependentChecks = @(
    @{ Name = "Build"; Script = "check-build.ps1" }
    @{ Name = "Code Quality"; Script = "check-code-quality.ps1" }
    @{ Name = "Test Coverage"; Script = "check-coverage.ps1" }
)

# Start static checks in parallel.
# Wrapped in try/catch so that if Start-Job fails mid-loop, already-started
# jobs are cleaned up instead of orphaned.
$staticJobs = @()
try {
    foreach ($check in $staticChecks) {
        $checkScript = Join-Path $hooksDir $check.Script
        $job = Start-Job -ScriptBlock {
            param($script, $workingDir)
            $ErrorActionPreference = "Stop"
            try {
                # Set working directory to repo root for relative paths to work
                Set-Location $workingDir
                $output = & $script *>&1 | Out-String
                @{ ExitCode = $LASTEXITCODE; Output = $output }
            }
            catch {
                @{ ExitCode = 1; Output = $_.Exception.Message }
            }
        } -ArgumentList $checkScript, $repoRoot
        
        $staticJobs += @{
            Name = $check.Name
            Job = $job
        }
    }
}
catch {
    Write-Host "Error starting parallel checks: $_" -ForegroundColor Red
    foreach ($jobInfo in $staticJobs) {
        Stop-Job $jobInfo.Job -ErrorAction SilentlyContinue
        Remove-Job $jobInfo.Job -Force -ErrorAction SilentlyContinue
    }
    exit 1
}

# Run build-dependent checks sequentially (abort on first failure)
$buildFailed = $false
foreach ($check in $buildDependentChecks) {
    Write-Host "  • $($check.Name)... " -ForegroundColor Gray
    
    try {
        $checkScript = Join-Path $hooksDir $check.Script
        # Stream output directly without buffering
        & $checkScript
        if ($LASTEXITCODE -eq 0) {
            $passed += $check.Name
        }
        else {
            $failed += $check.Name
            $allPassed = $false
            $buildFailed = $true
            Write-Host "  ⚡ Build/syntax failure — skipping remaining build-dependent checks" -ForegroundColor Yellow
            break
        }
    }
    catch {
        Write-Host "Error: $_" -ForegroundColor Red
        $failed += $check.Name
        $allPassed = $false
        $buildFailed = $true
        Write-Host "  ⚡ Build/syntax failure — skipping remaining build-dependent checks" -ForegroundColor Yellow
        break
    }
}

# Helper: clean up all remaining Start-Job processes to prevent resource leaks.
# On Windows, child processes are NOT auto-killed when the parent exits, so
# every Start-Job that isn't explicitly stopped leaks a full pwsh process.
function Stop-AllStaticJobs {
    foreach ($jobInfo in $staticJobs) {
        Stop-Job $jobInfo.Job -ErrorAction SilentlyContinue
        Remove-Job $jobInfo.Job -Force -ErrorAction SilentlyContinue
    }
}

# If build failed, stop parallel static jobs and exit early
if ($buildFailed) {
    Stop-AllStaticJobs
    Write-Host ""
    Write-Host "❌ Build failed: $($failed -join ', ') — downstream checks skipped" -ForegroundColor Red
    exit 1
}

# Wait for and process static checks results.
# Wrapped in try/finally so that ANY error (or Ctrl+C) during Wait-Job /
# Receive-Job still cleans up remaining background jobs instead of orphaning them.
try {
    foreach ($jobInfo in $staticJobs) {
        Write-Host "  • $($jobInfo.Name)... " -NoNewline -ForegroundColor Gray
        
        # Wait with timeout - 900s per job max (Windows Start-Job adds ~3x overhead)
        $result = $jobInfo.Job | Wait-Job -Timeout 900 | Receive-Job
        
        if ($null -eq $result) {
            # Timeout occurred
            Stop-Job $jobInfo.Job -ErrorAction SilentlyContinue
            Remove-Job $jobInfo.Job -Force -ErrorAction SilentlyContinue
            Write-Host "⏱ TIMEOUT" -ForegroundColor Yellow
            $failed += "$($jobInfo.Name) (timeout)"
            $allPassed = $false
            Write-Host "  ⚠️  This check took too long and was terminated to free resources" -ForegroundColor Yellow
        }
        else {
            Remove-Job $jobInfo.Job -ErrorAction SilentlyContinue
            
            if ($result.ExitCode -eq 0) {
                Write-Host "✓" -ForegroundColor Green
                $passed += $jobInfo.Name
            }
            else {
                Write-Host "✗" -ForegroundColor Red
                $failed += $jobInfo.Name
                $allPassed = $false
                if ($result.Output.Trim()) {
                    Write-Host ""
                    Write-Host $result.Output.Trim()
                    Write-Host ""
                }
            }
        }
    }
}
finally {
    # Ensure no orphaned pwsh processes remain regardless of how we exit
    Stop-AllStaticJobs
}

Write-Host ""

if ($allPassed) {
    Write-Host "✅ All checks passed" -ForegroundColor Green
    exit 0
}
else {
    Write-Host "❌ $($failed.Count) check(s) failed: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
