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
$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}

$testFiles = Get-StagedFiles -Pattern '(^tests/|/tests/|test_.*\.py$|_test\.py$)' `
    -DenyPatterns @('(venv|.venv|__pycache__|dist|build)') `
    -ResolveFullPath -RepoRoot $repoRoot

$stagedFiles = Get-StagedFiles -Pattern '\.py$' `
    -DenyPatterns @('(venv|.venv|__pycache__|dist|build)') `
    -SourceOnly

if ($testFiles.Count -gt 0) {
    Write-Host "🔍 Scanning staged test files for unmocked subprocess/git/bd calls..." -ForegroundColor Cyan
    $violations = @()

    foreach ($file in $testFiles) {
        $content = Get-Content $file -Raw
        $relPath = $file
        if ([IO.Path]::IsPathRooted($file)) {
            $relPath = $file -replace [regex]::Escape($repoRoot + [IO.Path]::DirectorySeparatorChar), ''
        }

        $hasSubprocessCall = [regex]::IsMatch($content, '(?m)\bsubprocess\.(run|Popen|call)\s*\(')
        $hasSubprocessMock = [regex]::IsMatch($content, '(?m)\b(monkeypatch|patch|Mock|MagicMock)\b')
        if ($hasSubprocessCall -and -not $hasSubprocessMock) {
            $violations += "${relPath}: subprocess.run/Popen/call without monkeypatch/patch/Mock"
        }

        $hasRunCommand = [regex]::IsMatch($content, '(?m)\b_run_(git|bd)\s*\(')
        $hasMonkeypatchSetattr = [regex]::IsMatch($content, '(?m)\bmonkeypatch\.setattr\s*\(')
        if ($hasRunCommand -and -not $hasMonkeypatchSetattr) {
            $violations += "${relPath}: _run_git/_run_bd without monkeypatch.setattr"
        }

        $hasOsSystem = [regex]::IsMatch($content, '(?m)\bos\.system\s*\(')
        if ($hasOsSystem) {
            $violations += "${relPath}: os.system call detected (not allowed in tests)"
        }
    }

    if ($violations.Count -gt 0) {
        Write-Host ""
        Write-Host "❌ Unmocked external calls detected in staged tests" -ForegroundColor Red
        Write-Host ""
        foreach ($v in $violations) {
            Write-Host "  $v" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "Mock subprocess and CLI calls in tests (use monkeypatch.setattr or unittest.mock.patch/Mock)." -ForegroundColor Cyan
        Write-Host "Example: tests/beads/test_beads_management.py" -ForegroundColor Cyan
        exit 1
    }

    Write-Host "✅ Test mocking scan passed" -ForegroundColor Green
}

if ($stagedFiles.Count -eq 0) {
    if ($testFiles.Count -eq 0) {
        Write-Host "No Python files staged for commit" -ForegroundColor Gray
    }
    else {
        Write-Host "No src Python files staged for commit" -ForegroundColor Gray
    }
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
