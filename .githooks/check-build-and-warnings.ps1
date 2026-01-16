#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Consolidated build and warning checker for C# projects
    
.DESCRIPTION
    Performs a single build that checks both:
    1. Build success (no compilation errors)
    2. Zero compiler warnings
    
    This consolidates what was previously done by check-build.ps1 and 
    check-compile-warnings.ps1 to eliminate duplicate builds.
    
.NOTES
    ⚠️  CRITICAL: This file is protected by CODEOWNERS
    Any modifications require @ameliapayne approval

.EXAMPLE
    .\.githooks\check-build-and-warnings.ps1
#>

$ErrorActionPreference = "Stop"

# Get repository root
$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}

$solutionFile = Join-Path $repoRoot "IcmMcpServer.sln"

if (-not (Test-Path $solutionFile)) {
    Write-Host "❌ Solution file not found: $solutionFile" -ForegroundColor Red
    exit 1
}

Write-Host "🔨 Building solution (checking for errors and warnings)..." -ForegroundColor Cyan

# Build the solution with detailed output to capture both errors and warnings
$buildOutput = dotnet build "$solutionFile" --no-incremental 2>&1 | Out-String

$buildFailed = $LASTEXITCODE -ne 0

# Check for build errors
$errorPattern = '(?m)^\s*.*?error\s+CS\d+:'
$errors = [regex]::Matches($buildOutput, $errorPattern)

# Check for warnings
$warningPattern = '(?m)^\s*.*?warning\s+CS\d+:'
$warnings = [regex]::Matches($buildOutput, $warningPattern)

# Report results
$hasIssues = $false

if ($buildFailed -or $errors.Count -gt 0) {
    Write-Host ""
    Write-Host "❌ BUILD FAILED" -ForegroundColor Red
    Write-Host ""
    if ($errors.Count -gt 0) {
        Write-Host "$($errors.Count) error(s):" -ForegroundColor Red
        foreach ($error in $errors) {
            Write-Host "  $($error.Value.Trim())" -ForegroundColor Red
        }
    }
    else {
        Write-Host "Build output:" -ForegroundColor Yellow
        Write-Host $buildOutput
    }
    Write-Host ""
    Write-Host "Fix the build errors before committing." -ForegroundColor Yellow
    $hasIssues = $true
}

if ($warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "❌ $($warnings.Count) compiler warning(s) found:" -ForegroundColor Red
    foreach ($warning in $warnings) {
        Write-Host "  $($warning.Value.Trim())" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "Fix all warnings before committing." -ForegroundColor Yellow
    $hasIssues = $true
}

if ($hasIssues) {
    exit 1
}

Write-Host "✅ Build successful with 0 warnings" -ForegroundColor Green
exit 0
