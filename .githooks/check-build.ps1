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

# Load shared utilities
foreach ($util in @("warning-utils.ps1", "staged-files-utils.ps1")) {
    $utilPath = Join-Path $PSScriptRoot $util
    if (-not (Test-Path $utilPath)) {
        throw "$util not found at $utilPath"
    }
    . $utilPath
}

$overallPassed = $true

$pythonFiles = Get-StagedFiles -Pattern '\.py$' `
    -DenyPatterns @('(worktrees|venv|\.venv|\.tox|__pycache__|dist|build|\.eggs)') `
    -ResolveFullPath -RepoRoot $repoRoot

if ($pythonFiles.Count -eq 0) {
    Write-Host "No Python files staged for commit; skipping syntax check" -ForegroundColor Gray
}
else {
    Write-Host "🔨 Checking Python syntax for $($pythonFiles.Count) files..." -ForegroundColor Cyan
    
    $errors = @()
    
    foreach ($file in $pythonFiles) {
        # Check syntax using Python's compile (warnings treated as errors)
        $result = python -W error -m py_compile "$file" 2>&1
        
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
            $relativePath = $error.File.Replace($repoRoot, "").TrimStart([char]'\', [char]'/')
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
