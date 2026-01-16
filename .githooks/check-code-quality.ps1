#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Code quality checker using ESLint for TypeScript/Node.js projects
    
.DESCRIPTION
    Checks staged TypeScript files for:
    - Code style violations (naming, formatting)
    - TypeScript best practices
    - Potential bugs
    - Unused variables/imports
    
    This script is designed to be called from a git pre-commit hook.
    
.EXAMPLE
    .\.githooks\check-code-quality.ps1
    
#>

param()

$ErrorActionPreference = "Stop"

# Get list of staged TypeScript files
function Get-StagedTypeScriptFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '\.ts$' } |
            Where-Object { $_ -match '^(src|tests)/' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}

# Main execution
$stagedFiles = Get-StagedTypeScriptFiles

if ($stagedFiles.Count -eq 0) {
    Write-Host "No TypeScript files staged for commit" -ForegroundColor Gray
    exit 0
}

Write-Host "🔍 Running ESLint on $($stagedFiles.Count) file(s)..." -ForegroundColor Cyan

# Run ESLint on staged files
$filesArg = $stagedFiles -join ' '
$lintOutput = npm run lint -- $filesArg 2>&1 | Out-String

$lintFailed = $LASTEXITCODE -ne 0

if ($lintFailed) {
    Write-Host ""
    Write-Host "❌ ESLINT ERRORS FOUND" -ForegroundColor Red
    Write-Host ""
    
    # Parse and display errors
    $lines = $lintOutput -split "`n"
    foreach ($line in $lines) {
        if ($line -match 'error' -or $line -match '✖') {
            Write-Host $line -ForegroundColor Red
        }
        elseif ($line -match 'warning' -or $line -match '⚠') {
            Write-Host $line -ForegroundColor Yellow
        }
        elseif ($line.Trim()) {
            Write-Host $line -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    Write-Host "Fix ESLint errors before committing." -ForegroundColor Yellow
    Write-Host "Tip: Run 'npm run lint -- --fix' to auto-fix some issues" -ForegroundColor Cyan
    exit 1
}

Write-Host "✅ ESLint passed" -ForegroundColor Green
exit 0
