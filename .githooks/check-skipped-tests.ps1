#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Check for skipped or xfailed tests in pytest test files
    
.DESCRIPTION
    Searches for skipped or xfailed tests and fails if any are found.
    This enforces a policy of no skipped or expected failures in the codebase.
    
    Tests can be skipped/xfailed using:
    - @pytest.mark.skip
    - @pytest.mark.skipif
    - @pytest.mark.xfail (also blocked)
    - pytest.skip() calls
    
.EXAMPLE
    .\.githooks\check-skipped-tests.ps1
    Checks for any skipped or xfailed tests
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
            
            # Check for @pytest.mark.xfail decorator (also forbidden)
            if ($line -match '@pytest\.mark\.xfail') {
                $testName = "Unknown"
                # Look ahead for the test function name
                # May need to look ahead multiple lines if xfail has arguments
                for ($j = $i + 1; $j -lt [Math]::Min($i + 5, $lines.Count); $j++) {
                    if ($lines[$j] -match 'def\s+(test_\w+)') {
                        $testName = $matches[1]
                        break
                    }
                }
                
                $skippedTests += @{
                    File = $file.Name
                    Line = $i + 1
                    Method = $testName
                    Type = "@pytest.mark.xfail"
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
        Write-Host "❌ $($skippedTests.Count) skipped/xfailed test(s) found" -ForegroundColor Red
        Write-Host ""
        foreach ($test in $skippedTests) {
            Write-Host "  $($test.File):$($test.Line) - $($test.Method) ($($test.Type))" -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "Fix: Remove @pytest.mark.skip, @pytest.mark.skipif, @pytest.mark.xfail decorators or pytest.skip() calls" -ForegroundColor Yellow
        Write-Host "     Tests must pass or be fixed - no exceptions allowed" -ForegroundColor Yellow
        exit 1
    }
    else {
        Write-Host "✅ No skipped or xfailed tests" -ForegroundColor Green
        exit 0
    }
}
catch {
    Write-Host "❌ Error: $_" -ForegroundColor Red
    exit 1
}
