#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Build checker for Python and desktop app
    
.DESCRIPTION
    Performs build validations:
    - Verifies all Python files have valid syntax
    - Checks for compilation errors
    - Validates Python code can be parsed
    - Runs desktop npm build when desktop assets are staged
    
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

# Get staged desktop files that should trigger a build
function Get-StagedDesktopBuildFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '^desktop/.*\.(ts|tsx|js|jsx|css|html)$' } |
            Where-Object { $_ -notmatch '(node_modules|dist|build)' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}

$overallPassed = $true

# Find Python files - exclude worktrees directory
$pythonFiles = Get-ChildItem -Path $repoRoot -Filter "*.py" -Recurse |
    Where-Object { $_.FullName -notmatch '\\(worktrees|venv|.venv|\.tox|__pycache__|dist|build|.eggs)\\' } |
    Select-Object -ExpandProperty FullName

if ($pythonFiles.Count -eq 0) {
    Write-Host "⚠️  No Python files found" -ForegroundColor Yellow
}
else {
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
        $overallPassed = $false
    }
    else {
        Write-Host "✅ All Python files have valid syntax" -ForegroundColor Green
    }
}

if (-not $overallPassed) {
    exit 1
}

$stagedDesktopFiles = Get-StagedDesktopBuildFiles

if ($stagedDesktopFiles.Count -eq 0) {
    Write-Host "No staged desktop build files detected; skipping desktop build" -ForegroundColor Gray
    exit 0
}

Write-Host "🛠  Building desktop app (npm run build) for $($stagedDesktopFiles.Count) staged file(s)..." -ForegroundColor Cyan

$desktopDir = Join-Path $repoRoot "desktop"

Push-Location $desktopDir
try {
    npm run build
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

Write-Host "✅ Desktop build succeeded" -ForegroundColor Green
exit 0
