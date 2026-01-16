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

# Get list of staged Python files
function Get-StagedPythonFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '\.py$' } |
            Where-Object { $_ -notmatch '(venv|.venv|__pycache__|dist|build)' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}

# Main execution
$stagedFiles = Get-StagedPythonFiles

if ($stagedFiles.Count -eq 0) {
    Write-Host "No Python files staged for commit" -ForegroundColor Gray
    exit 0
}

Write-Host "🔍 Running mypy type checking on $($stagedFiles.Count) file(s)..." -ForegroundColor Cyan

# Run mypy on staged files - each file separately
$mypyOutput = python -m mypy @stagedFiles --strict --show-error-codes --pretty 2>&1 | Out-String

$mypyFailed = $LASTEXITCODE -ne 0

if ($mypyFailed) {
    Write-Host ""
    Write-Host "❌ MYPY TYPE ERRORS FOUND" -ForegroundColor Red
    Write-Host ""
    
    # Parse and display errors
    $lines = $mypyOutput -split "`n"
    foreach ($line in $lines) {
        if ($line -match 'error:') {
            Write-Host $line -ForegroundColor Red
        }
        elseif ($line -match 'note:') {
            Write-Host $line -ForegroundColor Yellow
        }
        elseif ($line.Trim()) {
            Write-Host $line -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    Write-Host "Fix type checking errors before committing." -ForegroundColor Yellow
    Write-Host "Tips:" -ForegroundColor Cyan
    Write-Host "  • Add type annotations to function parameters and returns" -ForegroundColor Cyan
    Write-Host "  • Use 'from typing import ...' for complex types" -ForegroundColor Cyan
    Write-Host "  • Run 'python -m mypy <file>' locally to test" -ForegroundColor Cyan
    exit 1
}

Write-Host "✅ Type checking passed" -ForegroundColor Green
exit 0
