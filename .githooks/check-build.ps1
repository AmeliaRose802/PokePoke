#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Check if the project builds successfully
    
.DESCRIPTION
    Attempts to build the solution and fails if the build fails.
    This ensures that commits only include code that compiles successfully.

.EXAMPLE
    .\scripts\check-build.ps1
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

Write-Host "🔨 Building solution..." -ForegroundColor Cyan

# Build the solution
$buildOutput = dotnet build "$solutionFile" --no-incremental 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ BUILD FAILED" -ForegroundColor Red
    Write-Host ""
    Write-Host "Build output:" -ForegroundColor Yellow
    Write-Host $buildOutput
    Write-Host ""
    Write-Host "Fix the build errors before committing." -ForegroundColor Yellow
    exit 1
}

# Check for build errors in output (extra safety)
$errorLines = $buildOutput | Select-String -Pattern "error CS\d+:"
if ($errorLines) {
    Write-Host ""
    Write-Host "❌ BUILD ERRORS DETECTED" -ForegroundColor Red
    Write-Host ""
    $errorLines | ForEach-Object { Write-Host $_.Line -ForegroundColor Red }
    Write-Host ""
    exit 1
}

Write-Host "✅ Build successful" -ForegroundColor Green
exit 0
