#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Python syntax checker for Python projects
    
.DESCRIPTION
    Performs Python syntax validation:
    - Verifies all Python files have valid syntax
    - Checks for compilation errors
    - Validates Python code can be parsed
    
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

# Find Python files
$pythonFiles = Get-ChildItem -Path $repoRoot -Filter "*.py" -Recurse |
    Where-Object { $_.FullName -notmatch '\\(venv|.venv|\.tox|__pycache__|dist|build|.eggs)\\' } |
    Select-Object -ExpandProperty FullName

if ($pythonFiles.Count -eq 0) {
    Write-Host "⚠️  No Python files found" -ForegroundColor Yellow
    exit 0
}

Write-Host "🔨 Checking Python syntax for $($pythonFiles.Count) files..." -ForegroundColor Cyan

$errors = @()

foreach ($file in $pythonFiles) {
    # Check syntax using Python's compile
    $result = python -m py_compile "$file" 2>&1
    
    if ($LASTEXITCODE -ne 0) {
        $errors += @{
            File = $file
            Error = $result | Out-String
        }
    }
}

if ($errors.Count -gt 0) {
    Write-Host ""
    Write-Host "❌ SYNTAX ERRORS FOUND" -ForegroundColor Red
    Write-Host ""
    
    foreach ($error in $errors) {
        $relativePath = $error.File.Replace($repoRoot, "").TrimStart("\\", "/")
        Write-Host "  $relativePath" -ForegroundColor Red
        Write-Host "    $($error.Error.Trim())" -ForegroundColor Yellow
        Write-Host ""
    }
    
    Write-Host "Fix the Python syntax errors before committing." -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ All Python files have valid syntax" -ForegroundColor Green
exit 0
