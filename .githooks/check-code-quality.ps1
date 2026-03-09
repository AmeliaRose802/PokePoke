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
    -DenyPatterns @('(venv|.venv|__pycache__|dist|build)') `
    -SourceOnly

if ($stagedFiles.Count -eq 0) {
    Write-Host "No Python files staged for commit" -ForegroundColor Gray
    exit 0
}

Write-Host "🔍 Running mypy type checking on $($stagedFiles.Count) file(s)..." -ForegroundColor Cyan

# Ban `self: Any` in function signatures — use TYPE_CHECKING guard with the real class instead
$selfAnyViolations = @()
foreach ($file in $stagedFiles) {
    $lineNum = 0
    foreach ($line in (Get-Content $file)) {
        $lineNum++
        if ($line -match '^\s*def\s+\w+\s*\(\s*self\s*:\s*Any\b' -or
            $line -match '^\s*self\s*:\s*Any\s*,') {
            $relPath = $file -replace [regex]::Escape((git rev-parse --show-toplevel) + [IO.Path]::DirectorySeparatorChar), ''
            $selfAnyViolations += "${relPath}:${lineNum}: $($line.Trim())"
        }
    }
}

if ($selfAnyViolations.Count -gt 0) {
    Write-Host ""
    Write-Host "❌ BANNED PATTERN: self: Any" -ForegroundColor Red
    Write-Host ""
    foreach ($v in $selfAnyViolations) {
        Write-Host "  $v" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Use a TYPE_CHECKING guard with the real class instead:" -ForegroundColor Cyan
    Write-Host "  from typing import TYPE_CHECKING" -ForegroundColor Cyan
    Write-Host "  if TYPE_CHECKING:" -ForegroundColor Cyan
    Write-Host "      from .my_module import MyClass" -ForegroundColor Cyan
    Write-Host "  def my_method(self: MyClass, ...) -> ...:" -ForegroundColor Cyan
    exit 1
}

# Run mypy on staged files only (follows imports as needed for context)
# Use incremental cache for faster repeated runs
python -m mypy $stagedFiles --strict --show-error-codes --no-error-summary

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
