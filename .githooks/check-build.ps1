#!/usr/bin/env pwsh

<#
.SYNOPSIS
    TypeScript build checker for Node.js projects
    
.DESCRIPTION
    Performs TypeScript compilation check using tsc:
    - Verifies all TypeScript files compile without errors
    - Checks for type errors
    - Validates tsconfig.json settings
    
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

$tsconfigFile = Join-Path $repoRoot "tsconfig.json"

if (-not (Test-Path $tsconfigFile)) {
    Write-Host "❌ tsconfig.json not found: $tsconfigFile" -ForegroundColor Red
    exit 1
}

Write-Host "🔨 Building TypeScript project..." -ForegroundColor Cyan

# Build with TypeScript compiler
$buildOutput = npm run build 2>&1 | Out-String

$buildFailed = $LASTEXITCODE -ne 0

if ($buildFailed) {
    Write-Host ""
    Write-Host "❌ BUILD FAILED" -ForegroundColor Red
    Write-Host ""
    
    # Parse and highlight errors
    $lines = $buildOutput -split "`n"
    foreach ($line in $lines) {
        if ($line -match 'error TS\d+:') {
            Write-Host "  $($line.Trim())" -ForegroundColor Red
        }
        elseif ($line -match '^\s+\d+') {
            # Line number indicator
            Write-Host "  $($line.Trim())" -ForegroundColor Yellow
        }
    }
    
    Write-Host ""
    Write-Host "Fix the TypeScript compilation errors before committing." -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Build successful" -ForegroundColor Green
exit 0
