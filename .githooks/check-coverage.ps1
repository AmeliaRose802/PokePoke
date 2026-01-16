#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Pre-commit coverage checker for C# projects
    
.DESCRIPTION
    Runs tests and verifies that modified C# files have 80%+ coverage.
    This script is designed to be called from a git pre-commit hook.
    
.PARAMETER MinCoverage
    Minimum coverage percentage required (default: 80)
    
.EXAMPLE
    .\scripts\check-coverage.ps1
#>

param(
    [int]$MinCoverage = 80
)

$ErrorActionPreference = "Stop"

# Determine test results directory (agent-specific for parallel execution)
$agentId = if ($env:AGENT_NAME) { $env:AGENT_NAME } elseif ($env:TEST_SESSION_ID) { $env:TEST_SESSION_ID } else { "" }
if ($agentId) {
    $TestResultsDir = "./TestResults/$agentId"
} else {
    $TestResultsDir = "./TestResults"
}

# Get list of staged C# files (excluding test files)
function Get-StagedCSharpFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to get staged files"
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '\.cs$' } |
            Where-Object { $_ -match '^src/' } |
            Where-Object { $_ -notmatch '\.Test\.cs$' } |
            Where-Object { $_ -notmatch '/Tests/' } |
            Where-Object { $_ -notmatch 'icm_queue_tool/' } |
            Where-Object { $_ -notmatch '/Models/' } |
            Where-Object { $_ -notmatch 'Program\.cs$' } |
            Where-Object { $_ -notmatch 'Tool\.cs$' } |
            Where-Object { $_ -notmatch 'NamespaceDoc\.cs$' } |
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
        # Run dotnet test with coverage (--no-build since build already done by check-build-and-warnings.ps1)
        # Exclude slow integration tests (LiveKustoTests and CliIntegrationTests)
        $testOutput = dotnet test IcmMcpServer.sln --no-build --filter "FullyQualifiedName!~LiveKustoTests&FullyQualifiedName!~CliIntegrationTests" --collect:"XPlat Code Coverage" --results-directory:"$TestResultsDir" --logger:"console;verbosity=minimal" 2>&1
        
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
    
    # Find the most recent coverage file in agent-specific directory
    $coverageFiles = Get-ChildItem -Path "$TestResultsDir" -Recurse -Filter "coverage.cobertura.xml" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending
    
    if ($coverageFiles.Count -eq 0) {
        Write-Host "⚠️  No coverage file found in $TestResultsDir" -ForegroundColor Yellow
        return $true
    }
    
    $coverageFile = $coverageFiles[0].FullName
    
    # Parse coverage XML
    [xml]$coverage = Get-Content $coverageFile
    
    $failedFiles = @()
    $passedCount = 0
    
    foreach ($file in $Files) {
        # Convert path to match coverage report format
        $normalizedPath = $file -replace '/', '\'
        $fileName = Split-Path $normalizedPath -Leaf
        
        # Find matching class in coverage report
        $classes = $coverage.coverage.packages.package.classes.class |
            Where-Object { $_.filename -like "*$fileName" } |
            Where-Object { $_.name -notlike "*<>c*" } |  # Exclude compiler-generated closures
            Where-Object { $_.name -notlike "*<*>d__*" }  # Exclude compiler-generated async state machines
        
        if ($classes.Count -eq 0) {
            Write-Host "  ⚠️  $file - No coverage data found (may need tests)" -ForegroundColor Yellow
            $failedFiles += $file
            continue
        }
        
        $hasFailure = $false
        $fileFailures = @()
        
        foreach ($class in $classes) {
            $lineRate = [double]$class.'line-rate' * 100
            $className = $class.name
            
            if ($lineRate -lt $MinCoverage) {
                $fileFailures += "     ❌ [$className] Coverage: $([math]::Round($lineRate, 1))% (minimum: $MinCoverage%)"
                $hasFailure = $true
            }
        }
        
        if ($hasFailure) {
            Write-Host "  📁 $file" -ForegroundColor Cyan
            $fileFailures | ForEach-Object { Write-Host $_ -ForegroundColor Red }
            $failedFiles += $file
        }
        else {
            $passedCount++
        }
    }
    
    if ($failedFiles.Count -gt 0) {
        Write-Host "❌ $($failedFiles.Count) file(s) below $MinCoverage% coverage" -ForegroundColor Red
        return $false
    }
    
    Write-Host "PASS: Coverage $MinCoverage%+ ($passedCount files)" -ForegroundColor Green
    return $true
}

# Main execution
$stagedFiles = Get-StagedCSharpFiles

if ($stagedFiles.Count -eq 0) {
    exit 0
}

# Run tests
if (-not (Invoke-TestsWithCoverage)) {
    exit 1
}

# Check coverage
if (-not (Test-Coverage -Files $stagedFiles)) {
    exit 1
}

exit 0
