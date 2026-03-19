#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Build checker for desktop app
    
.DESCRIPTION
    Performs build validations:
    - Runs desktop npm build when desktop assets are staged
    
    Note: Python syntax validation is handled by ruff (E9xx rules)
    in the sequential pre-commit chain.
    
.NOTES
    ⚠️  CRITICAL: This file is protected by CODEOWNERS
    Any modifications require @ameliapayne approval

.EXAMPLE
    .\.githooks\check-build.ps1
#>

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

$stagedDesktopFiles = Get-StagedFiles -Pattern '^desktop/.*\.(ts|tsx|js|jsx|css|html)$' `
    -DenyPatterns @('(node_modules|dist|build)')

if ($stagedDesktopFiles.Count -eq 0) {
    Write-Host "No staged desktop build files detected; skipping desktop build" -ForegroundColor Gray
    exit 0
}

Write-Host "🛠  Building desktop app (npm run build) for $($stagedDesktopFiles.Count) staged file(s)..." -ForegroundColor Cyan

$desktopDir = Join-Path $repoRoot "desktop"
$buildOutputLines = @()

Push-Location $desktopDir
try {
    npm run build 2>&1 | Tee-Object -Variable buildOutputLines | Out-Default
    $buildExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($buildExitCode -ne 0) {
    Write-Host ""
    Write-Host "❌ Desktop build failed. Fix build errors before committing." -ForegroundColor Red
    exit 1
}

$warningLines = Get-WarningMatches -Lines $buildOutputLines
if ($warningLines.Count -gt 0) {
    Write-Host ""
    Write-Host "❌ Desktop build emitted warnings. Warnings must be resolved before committing." -ForegroundColor Red
    Write-Host ""
    foreach ($line in $warningLines) {
        Write-Host "  $line" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "✅ Desktop build succeeded" -ForegroundColor Green
exit 0
