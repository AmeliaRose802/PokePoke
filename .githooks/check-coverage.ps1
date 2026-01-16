#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Pre-commit coverage checker for Python projects
    
.DESCRIPTION
    Runs pytest with coverage and verifies that modified Python files have 80%+ coverage.
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

# Get list of staged Python files (excluding test files)
function Get-StagedPythonFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to get staged files"
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '\.py$' } |
            Where-Object { $_ -match '^src/pokepoke/' } |
            Where-Object { $_ -notmatch 'test_.*\.py$' } |
            Where-Object { $_ -notmatch '_test\.py$' } |
            Where-Object { $_ -notmatch '/tests/' } |
            Where-Object { $_ -notmatch '(venv|.venv|__pycache__)' } |
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
        
        # Run pytest with coverage - only JSON report to avoid terminal output hang
        python -m pytest --cov=src/pokepoke --cov-report=json -q
        $exitCode = $LASTEXITCODE
        
        if ($exitCode -ne 0) {
            Write-Host "❌ Tests failed" -ForegroundColor Red
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
    
    # Find pytest coverage summary
    $coverageFile = "coverage.json"
    
    if (-not (Test-Path $coverageFile)) {
        Write-Host "⚠️  No coverage summary found at $coverageFile" -ForegroundColor Yellow
        Write-Host "Run 'python -m pytest --cov=pokepoke --cov-report=json' to generate coverage data" -ForegroundColor Yellow
        return $false
    }
    
    # Parse coverage JSON
    $coverage = Get-Content $coverageFile -Raw | ConvertFrom-Json
    
    $failedFiles = @()
    $passedCount = 0
    
    foreach ($file in $Files) {
        # Convert to absolute path
        $repoRoot = git rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -ne 0) {
            $repoRoot = $PWD.Path
        }
        
        # Normalize path separators  
        $normalizedPath = $file -replace '/', '\'
        $fullPath = Join-Path $repoRoot $normalizedPath
        
        # Try to find coverage data for this file
        $fileData = $null
        $coverageFiles = $coverage.files.PSObject.Properties
        
        foreach ($key in $coverageFiles.Name) {
            $keyNormalized = $key -replace '/', '\'
            if ($keyNormalized -like "*$normalizedPath" -or $keyNormalized -eq $fullPath) {
                $fileData = $coverage.files.$key
                break
            }
        }
        
        if (-not $fileData) {
            Write-Host "  ⚠️  $file - No coverage data found (may need tests)" -ForegroundColor Yellow
            $failedFiles += $file
            continue
        }
        
        # Check line coverage percentage
        $lineCoverage = $fileData.summary.percent_covered
        
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
$stagedFiles = Get-StagedPythonFiles

if ($stagedFiles.Count -eq 0) {
    Write-Host "No Python source files staged for commit" -ForegroundColor Gray
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
