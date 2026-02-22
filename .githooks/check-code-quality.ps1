#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Code quality checker using mypy for Python type checking
    
.DESCRIPTION
    Checks staged Python files for:
    - Type annotation completeness
    - Type checking violations
    - Type hints best practices
    - Missing type annotations
    
    This script is designed to be called from a git pre-commit hook.
    
.EXAMPLE
    .\.githooks\check-code-quality.ps1
    
#>

param()

$ErrorActionPreference = "Stop"

# Load shared staged-file utilities
$stagedUtils = Join-Path $PSScriptRoot "staged-files-utils.ps1"
if (-not (Test-Path $stagedUtils)) {
    throw "staged-files-utils.ps1 not found at $stagedUtils"
}
. $stagedUtils

# Main execution
$stagedFiles = Get-StagedFiles -Pattern '\.py$' `
    -DenyPatterns @('(venv|.venv|__pycache__|dist|build)')

if ($stagedFiles.Count -eq 0) {
    Write-Host "No Python files staged for commit" -ForegroundColor Gray
    exit 0
}

Write-Host "🔍 Running mypy type checking on $($stagedFiles.Count) file(s)..." -ForegroundColor Cyan

# Run mypy on src/pokepoke package (not individual files) to handle imports properly
python -m mypy src/pokepoke --strict --show-error-codes --pretty

$mypyFailed = $LASTEXITCODE -ne 0

if ($mypyFailed) {
    Write-Host ""
    Write-Host "❌ MYPY TYPE ERRORS FOUND" -ForegroundColor Red
    Write-Host ""
    Write-Host "Fix type checking errors before committing." -ForegroundColor Yellow
    Write-Host "Tips:" -ForegroundColor Cyan
    Write-Host "  • Add type annotations to function parameters and returns" -ForegroundColor Cyan
    Write-Host "  • Use 'from typing import ...' for complex types" -ForegroundColor Cyan
    Write-Host "  • Run 'python -m mypy src/pokepoke' locally to test" -ForegroundColor Cyan
    exit 1
}

Write-Host "✅ Type checking passed" -ForegroundColor Green
exit 0
