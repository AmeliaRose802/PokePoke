#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Verify integrity of quality gate scripts
    
.DESCRIPTION
    Checks that quality gate scripts have not been tampered with:
    - No bypass parameters (SkipCheck, SKIP_*, etc.)
    - No exclusion patterns added to file filters
    - Coverage thresholds not lowered
    - No files added to ignore lists
    
.NOTES
    ⚠️  This file is protected by CODEOWNERS
    
.EXAMPLE
    .\.githooks\verify-integrity.ps1
#>

$ErrorActionPreference = "Stop"

$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}

$hooksDir = Join-Path $repoRoot ".githooks"

# Define forbidden patterns that indicate tampering
$forbiddenPatterns = @{
    "Bypass Parameters" = @(
        'param\s*\(\s*\[switch\]\s*\$SkipCheck',
        '\$env:SKIP_',
        'if\s*\(\s*\$SkipCheck\s*\)',
        '-SkipCheck\b',
        '-NoVerify\b',
        'Allow bypass',
        'Bypass.*check'
    )
    "Coverage Threshold Manipulation" = @(
        '\[int\]\s*\$MinCoverage\s*=\s*[0-7][0-9]',  # Below 80
        'MinCoverage\s*=\s*[0-7][0-9]'
    )
    "File Exclusion Patterns" = @(
        'Where-Object\s*{[^}]*-notmatch[^}]*}.*#\s*EXCLUDE',
        'excludePattern',
        'skipFile',
        'ignoreFile'
    )
    "Early Exit Bypass" = @(
        'exit\s+0.*#.*skip',
        'return\s+\$true.*#.*bypass',
        'if.*SKIP.*exit\s+0'
    )
}

$violations = @()
$scriptsToCheck = @(
    "check-coverage.ps1",
    "check-code-quality.ps1",
    "check-file-length.ps1",
    "check-skipped-tests.ps1",
    "check-build.ps1"
    # NOTE: pre-commit.ps1 and verify-integrity.ps1 are excluded as they
    # legitimately contain these patterns for detection purposes
)

Write-Host "Verifying quality gate script integrity..." -ForegroundColor Cyan
Write-Host ""

foreach ($script in $scriptsToCheck) {
    $scriptPath = Join-Path $hooksDir $script
    
    if (-not (Test-Path $scriptPath)) {
        $violations += @{
            Script = $script
            Type = "Missing File"
            Details = "Critical quality gate script is missing"
        }
        continue
    }
    
    $content = Get-Content $scriptPath -Raw
    
    foreach ($category in $forbiddenPatterns.Keys) {
        foreach ($pattern in $forbiddenPatterns[$category]) {
            if ($content -match $pattern) {
                $violations += @{
                    Script = $script
                    Type = $category
                    Details = "Matched forbidden pattern: '$($matches[0])'"
                    Pattern = $pattern
                }
            }
        }
    }
}

if ($violations.Count -eq 0) {
    Write-Host "✅ All quality gate scripts verified - no tampering detected" -ForegroundColor Green
    exit 0
}

# Report violations
Write-Host "🚨 SECURITY VIOLATION: Quality gate tampering detected!" -ForegroundColor Red
Write-Host ""
Write-Host "The following violations were found:" -ForegroundColor Red
Write-Host ""

$groupedViolations = $violations | Group-Object -Property Type

foreach ($group in $groupedViolations) {
    Write-Host "[$($group.Name)]" -ForegroundColor Yellow
    foreach ($violation in $group.Group) {
        Write-Host "  • $($violation.Script): $($violation.Details)" -ForegroundColor Red
    }
    Write-Host ""
}

Write-Host "❌ COMMIT BLOCKED" -ForegroundColor Red
Write-Host ""
Write-Host "Quality gate scripts MUST NOT be modified to bypass checks." -ForegroundColor Red
Write-Host "Any modifications to .githooks/ require admin approval via CODEOWNERS." -ForegroundColor Red
Write-Host "YOU KNOW WHAT YOU DID!." -ForegroundColor Red

exit 1
