#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Ruff linter check for staged Python files

.DESCRIPTION
    Runs ruff on staged Python files to enforce code style and catch
    common errors (E, F, W rule categories).

.EXAMPLE
    .\.githooks\check-ruff.ps1
#>

param()

$ErrorActionPreference = "Stop"

# Load shared staged-file utilities
$stagedUtils = Join-Path $PSScriptRoot "staged-files-utils.ps1"
if (-not (Test-Path $stagedUtils)) {
    throw "staged-files-utils.ps1 not found at $stagedUtils"
}
. $stagedUtils

$stagedFiles = Get-StagedFiles -Pattern '\.py$' `
    -DenyPatterns @('(venv|.venv|__pycache__|dist|build|worktrees)')

if ($stagedFiles.Count -eq 0) {
    Write-Host "No Python files staged for commit" -ForegroundColor Gray
    exit 0
}

Write-Host "🔍 Running ruff on $($stagedFiles.Count) file(s)..." -ForegroundColor Cyan

python -m ruff check $stagedFiles --output-format=concise --cache-dir /dev/null

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ RUFF LINT ERRORS FOUND (MANDATORY - NO EXCEPTIONS)" -ForegroundColor Red
    Write-Host ""
    Write-Host "ALL ruff violations must be fixed before committing." -ForegroundColor Yellow
    Write-Host "Tips:" -ForegroundColor Cyan
    Write-Host "  • Run 'python -m ruff check src/ tests/' locally to see all errors" -ForegroundColor Cyan
    Write-Host "  • Run 'python -m ruff check src/ tests/ --fix' to auto-fix many errors" -ForegroundColor Cyan
    exit 1
}

Write-Host "✅ Ruff linting passed" -ForegroundColor Green
exit 0
