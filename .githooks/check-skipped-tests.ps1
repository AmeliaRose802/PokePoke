#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Check for skipped tests in Jest test files
    
.DESCRIPTION
    Searches for skipped tests and fails if any tests are skipped.
    This enforces a policy of no skipped tests in the codebase.
    
    Tests can be skipped using:
    - describe.skip()
    - it.skip() / test.skip()
    - xit() / xtest() / xdescribe()
    
.EXAMPLE
    .\.githooks\check-skipped-tests.ps1
    Checks for any skipped tests
#>

$ErrorActionPreference = "Stop"

try {
    # Search test files for skip patterns
    $testFiles = @()
    $testFiles += Get-ChildItem -Path "tests" -Filter "*.spec.ts" -Recurse -ErrorAction SilentlyContinue
    $testFiles += Get-ChildItem -Path "tests" -Filter "*.test.ts" -Recurse -ErrorAction SilentlyContinue
    $testFiles += Get-ChildItem -Path "src" -Filter "*.spec.ts" -Recurse -ErrorAction SilentlyContinue
    $testFiles += Get-ChildItem -Path "src" -Filter "*.test.ts" -Recurse -ErrorAction SilentlyContinue
    
    $testFiles = $testFiles | Where-Object { $_.FullName -notmatch '\\(node_modules|dist|coverage)\\' }
    
    $skippedTests = @()
    
    foreach ($file in $testFiles) {
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        $lines = Get-Content $file.FullName -ErrorAction SilentlyContinue
        
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $line = $lines[$i]
            
            # Check for .skip() patterns
            if ($line -match '\b(describe|it|test)\.skip\s*\(') {
                $testName = "Unknown"
                if ($line -match '\.skip\s*\(\s*[''"]([^''"]+)[''"]') {
                    $testName = $matches[1]
                }
                
                $skippedTests += @{
                    File = $file.Name
                    Line = $i + 1
                    Method = $testName
                    Type = ".skip()"
                }
            }
            
            # Check for x-prefixed patterns (xit, xtest, xdescribe)
            if ($line -match '\b(xit|xtest|xdescribe)\s*\(') {
                $testName = "Unknown"
                if ($line -match '\b(xit|xtest|xdescribe)\s*\(\s*[''"]([^''"]+)[''"]') {
                    $testName = $matches[2]
                }
                
                $skippedTests += @{
                    File = $file.Name
                    Line = $i + 1
                    Method = $testName
                    Type = $matches[1]
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
        Write-Host "Fix: Remove .skip() or x-prefix from tests" -ForegroundColor Yellow
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
