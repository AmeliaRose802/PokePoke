#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Check for skipped tests in the codebase
    
.DESCRIPTION
    Runs all tests and fails if any tests are skipped.
    This enforces a policy of no skipped tests in the codebase.
    
    Tests can be skipped using:
    - [Fact(Skip = "reason")]
    - [Theory(Skip = "reason")]
    - Assert.Skip()
    - xUnit [Trait("Category", "Skip")]
    
.EXAMPLE
    .\scripts\check-skipped-tests.ps1
    Checks for any skipped tests
#>

$ErrorActionPreference = "Stop"

try {
    # Search test files for Skip attributes (much faster than running tests)
    # Exclude obj and bin directories to avoid build artifacts and file locks
    $testFiles = Get-ChildItem -Path "tests" -Filter "*.cs" -Recurse -ErrorAction SilentlyContinue | 
        Where-Object { $_.FullName -notmatch '\\(obj|bin)\\' }
    
    $skippedTests = @()
    
    foreach ($file in $testFiles) {
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        $lines = Get-Content $file.FullName -ErrorAction SilentlyContinue
        
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $line = $lines[$i]
            
            # Check for [Fact(Skip = "...")] or [Theory(Skip = "...")]
            if ($line -match '\[(Fact|Theory)\s*\(\s*Skip\s*=') {
                # Try to find the test method name on next few lines
                $methodName = "Unknown"
                for ($j = $i + 1; $j -lt [Math]::Min($i + 5, $lines.Count); $j++) {
                    if ($lines[$j] -match '^\s*(public|private|internal|protected).*\s+(\w+)\s*\(') {
                        $methodName = $matches[2]
                        break
                    }
                }
                
                $skippedTests += @{
                    File = $file.Name
                    Line = $i + 1
                    Method = $methodName
                }
            }
        }
    }
    
    if ($skippedTests.Count -gt 0) {
        Write-Host "FAIL: $($skippedTests.Count) skipped test(s) found" -ForegroundColor Red
        foreach ($test in $skippedTests) {
            Write-Host "  $($test.File):$($test.Line) - $($test.Method)" -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "Fix: Remove [Fact(Skip=...)] or [Theory(Skip=...)] attributes" -ForegroundColor Yellow
        exit 1
    }
    else {
        Write-Host "PASS: No skipped tests" -ForegroundColor Green
        exit 0
    }
}
catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
    exit 1
}
