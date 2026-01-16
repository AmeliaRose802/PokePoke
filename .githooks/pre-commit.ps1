#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Git pre-commit hook for PokePoke Python project
    
.DESCRIPTION
    Runs the following checks before allowing a commit:
    1. Integrity check (verifies quality scripts haven't been tampered with)
    2. Build check (Python syntax validation)
    3. Code quality check (mypy type checking)
    4. Skipped tests check (no skipped pytest tests)
    5. Test coverage check (modified files must have 80%+ coverage)

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

Write-Host "Pre-commit checks:" -ForegroundColor Cyan

# INTEGRITY CHECK: Verify no bypass parameters exist in quality scripts
Write-Host "  • Integrity Check... " -NoNewline -ForegroundColor Gray
$hooksDir = Join-Path $repoRoot ".githooks"
$bypassPatterns = @(
    'param\s*\(\s*\[switch\]\s*\$SkipCheck',
    '\$env:SKIP_',
    'if\s*\(\s*\$SkipCheck\s*\)',
    '-SkipCheck',
    'bypass',
    'Allow bypass'
)

$integrityViolations = @()
$scriptsToCheck = @("check-coverage.ps1", "check-code-quality.ps1", "check-file-length.ps1")

foreach ($script in $scriptsToCheck) {
    $scriptPath = Join-Path $hooksDir $script
    if (Test-Path $scriptPath) {
        $content = Get-Content $scriptPath -Raw
        foreach ($pattern in $bypassPatterns) {
            if ($content -match $pattern) {
                $integrityViolations += "$script contains bypass mechanism: '$($matches[0])'"
            }
        }
    }
}

if ($integrityViolations.Count -gt 0) {
    Write-Host "✗" -ForegroundColor Red
    Write-Host ""
    Write-Host "🚨 SECURITY VIOLATION: Quality gate scripts have been tampered with!" -ForegroundColor Red
    Write-Host ""
    foreach ($violation in $integrityViolations) {
        Write-Host "  • $violation" -ForegroundColor Red
    }
    Write-Host ""
    Write-Host "Quality gate scripts MUST NOT contain bypass mechanisms." -ForegroundColor Red
    Write-Host "Any modifications to .githooks/ require admin approval via CODEOWNERS." -ForegroundColor Red
    Write-Host ""
    Write-Host "To fix: Restore scripts from git history or main branch." -ForegroundColor Yellow
    Write-Host "  git checkout origin/main .githooks/" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}
Write-Host "✓" -ForegroundColor Green

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

# Checks that don't depend on build artifacts - can run in parallel
$staticChecks = @(
    @{ Name = "Code Quality"; Script = "check-code-quality.ps1" }
    @{ Name = "Skipped Tests"; Script = "check-skipped-tests.ps1" }
    @{ Name = "File Length"; Script = "check-file-length.ps1" }
)

# Checks that need build artifacts or must run in sequence
$buildDependentChecks = @(
    @{ Name = "Build"; Script = "check-build.ps1" }
    @{ Name = "Test Coverage"; Script = "check-coverage.ps1" }
)

# Start static checks in parallel
$staticJobs = @()
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

# Run build-dependent checks sequentially
foreach ($check in $buildDependentChecks) {
    Write-Host "  • $($check.Name)... " -NoNewline -ForegroundColor Gray
    
    try {
        $checkScript = Join-Path $hooksDir $check.Script
        $output = & $checkScript *>&1 | Out-String
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓" -ForegroundColor Green
            $passed += $check.Name
        }
        else {
            Write-Host "✗" -ForegroundColor Red
            $failed += $check.Name
            $allPassed = $false
            # Show output only for failed checks
            if ($output.Trim()) {
                Write-Host ""
                Write-Host $output.Trim()
                Write-Host ""
            }
        }
    }
    catch {
        Write-Host "✗" -ForegroundColor Red
        Write-Host "    Error: $_" -ForegroundColor Red
        $failed += $check.Name
        $allPassed = $false
    }
}

# Wait for and process static checks results
foreach ($jobInfo in $staticJobs) {
    Write-Host "  • $($jobInfo.Name)... " -NoNewline -ForegroundColor Gray
    
    $result = Wait-Job $jobInfo.Job | Receive-Job
    Remove-Job $jobInfo.Job
    
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

Write-Host ""

if ($allPassed) {
    Write-Host "✅ All checks passed" -ForegroundColor Green
    exit 0
}
else {
    Write-Host "❌ $($failed.Count) check(s) failed: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
