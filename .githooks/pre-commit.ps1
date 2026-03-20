#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Git pre-commit hook for PokePoke Python project
    
.DESCRIPTION
    Runs the following checks before allowing a commit:
    1. Integrity check (verifies quality scripts haven't been tampered with)
    2. Ruff lint check (syntax + style) [sequential]
    3. Code quality check (mypy type checking) [sequential, after ruff]
    4. Test coverage check (modified files must have 80%+ coverage) [sequential, after mypy]
    5. Skipped tests check [sequential]
    6. Desktop build check [sequential]
    7. File length check [sequential]
    8. Desktop lint check [sequential]
    9. Pokepoke boot check [sequential]

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

# Static checks that don't depend on build artifacts - run sequentially
$staticChecks = @(
    @{ Name = "Pokepoke Boot"; Script = "check-pokepoke-import.ps1" }
    @{ Name = "Skipped Tests"; Script = "check-skipped-tests.ps1" }
    @{ Name = "File Length"; Script = "check-file-length.ps1" }
    @{ Name = "Desktop ESLint"; Script = "check-desktop-lint.ps1" }
    @{ Name = "Desktop Build"; Script = "check-build.ps1" }
)

# Sequential chain: ruff -> mypy -> coverage
# Ruff catches syntax errors (E9xx) so py_compile is unnecessary.
# If any step fails, remaining checks are skipped (early exit on first failure).
$buildDependentChecks = @(
    @{ Name = "Ruff Lint"; Script = "check-ruff.ps1" }
    @{ Name = "Code Quality"; Script = "check-code-quality.ps1" }
    @{ Name = "Test Coverage"; Script = "check-coverage.py"; Interpreter = "python" }
)

# Run build-dependent checks sequentially (abort on first failure)
$buildFailed = $false
foreach ($check in $buildDependentChecks) {
    Write-Host "  • $($check.Name)... " -ForegroundColor Gray
    $checkStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    
    try {
        $checkScript = Join-Path $hooksDir $check.Script
        # Stream output directly without buffering
        if ($check.Interpreter) {
            & $check.Interpreter $checkScript
        } else {
            & $checkScript
        }
        $checkStopwatch.Stop()
        if ($LASTEXITCODE -eq 0) {
            Write-Host "    ⏱ $($check.Name): $([math]::Round($checkStopwatch.Elapsed.TotalSeconds, 1))s" -ForegroundColor DarkGray
            $passed += $check.Name
        }
        else {
            Write-Host "    ⏱ $($check.Name): $([math]::Round($checkStopwatch.Elapsed.TotalSeconds, 1))s" -ForegroundColor DarkGray
            $failed += $check.Name
            $allPassed = $false
            $buildFailed = $true
            Write-Host "  ⚡ Build/syntax failure — skipping remaining build-dependent checks" -ForegroundColor Yellow
            break
        }
    }
    catch {
        $checkStopwatch.Stop()
        Write-Host "    ⏱ $($check.Name): $([math]::Round($checkStopwatch.Elapsed.TotalSeconds, 1))s" -ForegroundColor DarkGray
        Write-Host "Error: $_" -ForegroundColor Red
        $failed += $check.Name
        $allPassed = $false
        $buildFailed = $true
        Write-Host "  ⚡ Build/syntax failure — skipping remaining build-dependent checks" -ForegroundColor Yellow
        break
    }
}

# If build failed, exit early
if ($buildFailed) {
    Write-Host ""
    Write-Host "❌ Build failed: $($failed -join ', ') — downstream checks skipped" -ForegroundColor Red
    exit 1
}

# Run static checks sequentially (no Start-Job overhead)
foreach ($check in $staticChecks) {
    Write-Host "  • $($check.Name)... " -NoNewline -ForegroundColor Gray
    $checkStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    
    try {
        $checkScript = Join-Path $hooksDir $check.Script
        # Capture output but don't stream (these checks are fast)
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
        }
    }
    catch {
        $checkStopwatch.Stop()
        Write-Host "✗" -ForegroundColor Red
        Write-Host "Error: $_" -ForegroundColor Red
        $failed += $check.Name
        $allPassed = $false
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
