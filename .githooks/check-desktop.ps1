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

# Load shared warning detection helpers
$warningHelper = Join-Path $PSScriptRoot "warning-utils.ps1"
if (-not (Test-Path $warningHelper)) {
    throw "warning-utils.ps1 not found at $warningHelper"
}
. $warningHelper

# Get list of staged desktop TypeScript files
function Get-StagedDesktopTsFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '^desktop/.*\.(ts|tsx)$' } |
            Where-Object { $_ -notmatch '(node_modules|dist|build)' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}

# Main execution
$stagedFiles = Get-StagedDesktopTsFiles

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
