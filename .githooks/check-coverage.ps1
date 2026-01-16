#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Pre-commit coverage checker for TypeScript/Node.js projects
    
.DESCRIPTION
    Runs Jest tests with coverage and verifies that modified TypeScript files have 80%+ coverage.
    This script is designed to be called from a git pre-commit hook.
    
.PARAMETER MinCoverage
    Minimum coverage percentage required (default: 80)
    
.EXAMPLE
    .\.githooks\check-coverage.ps1
#>

param(
    [int]$MinCoverage = 80
)

$ErrorActionPreference = "Stop"

# Get list of staged TypeScript files (excluding test files)
function Get-StagedTypeScriptFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to get staged files"
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '\.ts$' } |
            Where-Object { $_ -match '^src/' } |
            Where-Object { $_ -notmatch '\.spec\.ts$' } |
            Where-Object { $_ -notmatch '\.test\.ts$' } |
            Where-Object { $_ -notmatch '/tests/' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}

# Run tests with coverage
function Invoke-TestsWithCoverage {
    try {
        Write-Host "🧪 Running tests with coverage..." -ForegroundColor Cyan
        
        # Run Jest with coverage
        $testOutput = npm run test:coverage 2>&1 | Out-String
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ Tests failed" -ForegroundColor Red
            Write-Host $testOutput
            return $false
        }
        
        return $true
    }
    catch {
        Write-Host "❌ Test execution failed: $_" -ForegroundColor Red
        return $false
    }
}

# Check coverage for modified files
function Test-Coverage {
    param([string[]]$Files)
    
    if ($Files.Count -eq 0) {
        return $true
    }
    
    # Find Jest coverage summary
    $coverageDir = "coverage"
    $coverageSummary = Join-Path $coverageDir "coverage-summary.json"
    
    if (-not (Test-Path $coverageSummary)) {
        Write-Host "⚠️  No coverage summary found at $coverageSummary" -ForegroundColor Yellow
        Write-Host "Run 'npm run test:coverage' to generate coverage data" -ForegroundColor Yellow
        return $false
    }
    
    # Parse coverage JSON
    $coverage = Get-Content $coverageSummary -Raw | ConvertFrom-Json
    
    $failedFiles = @()
    $passedCount = 0
    
    foreach ($file in $Files) {
        # Jest uses absolute paths in coverage, convert to match
        $repoRoot = git rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -ne 0) {
            $repoRoot = $PWD.Path
        }
        
        # Normalize path separators
        $normalizedPath = $file -replace '/', '\'
        $fullPath = Join-Path $repoRoot $normalizedPath
        
        # Try to find coverage data for this file
        $fileData = $null
        foreach ($key in $coverage.PSObject.Properties.Name) {
            if ($key -like "*$normalizedPath" -or $key -eq $fullPath) {
                $fileData = $coverage.$key
                break
            }
        }
        
        if (-not $fileData) {
            Write-Host "  ⚠️  $file - No coverage data found (may need tests)" -ForegroundColor Yellow
            $failedFiles += $file
            continue
        }
        
        # Check line coverage
        $lineCoverage = $fileData.lines.pct
        
        if ($lineCoverage -lt $MinCoverage) {
            Write-Host "  ❌ $file - Coverage: $lineCoverage% (minimum: $MinCoverage%)" -ForegroundColor Red
            $failedFiles += $file
        }
        else {
            $passedCount++
        }
    }
    
    if ($failedFiles.Count -gt 0) {
        Write-Host ""
        Write-Host "❌ $($failedFiles.Count) file(s) below $MinCoverage% coverage" -ForegroundColor Red
        Write-Host ""
        Write-Host "Add tests to increase coverage for these files." -ForegroundColor Yellow
        return $false
    }
    
    Write-Host "✅ Coverage $MinCoverage%+ ($passedCount files)" -ForegroundColor Green
    return $true
}

# Main execution
$stagedFiles = Get-StagedTypeScriptFiles

if ($stagedFiles.Count -eq 0) {
    Write-Host "No TypeScript source files staged for commit" -ForegroundColor Gray
    exit 0
}

Write-Host "Checking coverage for $($stagedFiles.Count) staged file(s)..." -ForegroundColor Cyan

# Run tests
if (-not (Invoke-TestsWithCoverage)) {
    exit 1
}

# Check coverage
if (-not (Test-Coverage -Files $stagedFiles)) {
    exit 1
}

exit 0
