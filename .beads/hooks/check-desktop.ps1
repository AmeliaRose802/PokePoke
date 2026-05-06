#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Desktop TypeScript type-check for pre-commit hook
    
.DESCRIPTION
    Checks staged desktop TypeScript/TSX files for:
    - TypeScript compilation errors
    - Type safety violations
    - Strict mode compliance (strictNullChecks, noImplicitAny, etc.)
    
    This script is designed to be called from a git pre-commit hook.
    
.EXAMPLE
    .\.githooks\check-desktop.ps1
    
#>

param()

$ErrorActionPreference = "Stop"

# Get repository root
$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}

# Load shared utilities
foreach ($util in @("warning-utils.ps1", "staged-files-utils.ps1")) {
    $utilPath = Join-Path $PSScriptRoot $util
    if (-not (Test-Path $utilPath)) {
        throw "$util not found at $utilPath"
    }
    . $utilPath
}

# Main execution
$stagedFiles = Get-StagedFiles -Pattern '^desktop/.*\.(ts|tsx)$' `
    -DenyPatterns @('(node_modules|dist|build)')

if ($stagedFiles.Count -eq 0) {
    Write-Host "No desktop TypeScript files staged for commit" -ForegroundColor Gray
    exit 0
}

Write-Host "🔍 Running TypeScript type-check on $($stagedFiles.Count) desktop file(s)..." -ForegroundColor Cyan

# Change to desktop directory and run tsc
$desktopDir = Join-Path $repoRoot "desktop"
$tscOutputLines = @()

Push-Location $desktopDir
try {
    # Run TypeScript compiler in check-only mode using project references
    npx tsc -b --noEmit 2>&1 | Tee-Object -Variable tscOutputLines | Out-Default
    $tscExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($tscExitCode -ne 0) {
    Write-Host ""
    Write-Host "❌ TYPESCRIPT TYPE ERRORS FOUND" -ForegroundColor Red
    Write-Host ""
    Write-Host "Fix type checking errors before committing." -ForegroundColor Yellow
    Write-Host "Tips:" -ForegroundColor Cyan
    Write-Host "  • Check for null/undefined handling (strictNullChecks enabled)" -ForegroundColor Cyan
    Write-Host "  • Add explicit types to function parameters and returns" -ForegroundColor Cyan
    Write-Host "  • Run 'cd desktop && npx tsc -b --noEmit' locally to test" -ForegroundColor Cyan
    exit 1
}

$warningLines = Get-WarningMatches -Lines $tscOutputLines
if ($warningLines.Count -gt 0) {
    Write-Host ""
    Write-Host "❌ TypeScript compiler emitted warnings. Resolve warnings before committing." -ForegroundColor Red
    Write-Host ""
    foreach ($line in $warningLines) {
        Write-Host "  $line" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "✅ Desktop TypeScript type-check passed" -ForegroundColor Green
exit 0
