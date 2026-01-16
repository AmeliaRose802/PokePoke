#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Check for skipped tests in pytest test files
    
.DESCRIPTION
    Searches for skipped tests and fails if any tests are skipped.
    This enforces a policy of no skipped tests in the codebase.
    
    Tests can be skipped using:
    - @pytest.mark.skip
    - @pytest.mark.skipif
    - pytest.skip() calls
    
.EXAMPLE
    .\.githooks\check-skipped-tests.ps1
    Checks for any skipped tests
#>

$ErrorActionPreference = "Stop"

try {
    # Search test files for skip patterns
    $testFiles = @()
    $testFiles += Get-ChildItem -Path "." -Filter "test_*.py" -Recurse -ErrorAction SilentlyContinue
    $testFiles += Get-ChildItem -Path "." -Filter "*_test.py" -Recurse -ErrorAction SilentlyContinue
    
    $testFiles = $testFiles | Where-Object { $_.FullName -notmatch '\\(venv|.venv|__pycache__|dist|build)\\' }
    
    $skippedTests = @()
    
    foreach ($file in $testFiles) {
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        $lines = Get-Content $file.FullName -ErrorAction SilentlyContinue
        
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $line = $lines[$i]
            
            # Check for @pytest.mark.skip decorator
            if ($line -match '@pytest\.mark\.skip') {
                $testName = "Unknown"
                # Look ahead for the test function name
                if ($i + 1 -lt $lines.Count -and $lines[$i + 1] -match 'def\s+(test_\w+)') {
                    $testName = $matches[1]
                }
                
                $skippedTests += @{
                    File = $file.Name
                    Line = $i + 1
                    Method = $testName
                    Type = "@pytest.mark.skip"
                }
            }
            
            # Check for @pytest.mark.skipif decorator
            if ($line -match '@pytest\.mark\.skipif') {
                $testName = "Unknown"
                # Look ahead for the test function name
                if ($i + 1 -lt $lines.Count -and $lines[$i + 1] -match 'def\s+(test_\w+)') {
                    $testName = $matches[1]
                }
                
                $skippedTests += @{
                    File = $file.Name
                    Line = $i + 1
                    Method = $testName
                    Type = "@pytest.mark.skipif"
                }
            }
            
            # Check for pytest.skip() calls
            if ($line -match 'pytest\.skip\s*\(') {
                $skippedTests += @{
                    File = $file.Name
                    Line = $i + 1
                    Method = "Inline skip"
                    Type = "pytest.skip()"
                }
            }
        }
    }
    
    if ($skippedTests.Count -gt 0) {
        Write-Host "❌ $($skippedTests.Count) skipped test(s) found" -ForegroundColor Red
        Write-Host ""
        foreach ($test in $skippedTests) {
            Write-Host "  $($test.File):$($test.Line) - $($test.Method) ($($test.Type))" -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "Fix: Remove @pytest.mark.skip, @pytest.mark.skipif decorators or pytest.skip() calls" -ForegroundColor Yellow
        exit 1
    }
    else {
        Write-Host "✅ No skipped tests" -ForegroundColor Green
        exit 0
    }
}
catch {
    Write-Host "❌ Error: $_" -ForegroundColor Red
    exit 1
}
