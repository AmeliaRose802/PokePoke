#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Pre-commit compile warning checker for C# projects
    
.DESCRIPTION
    Builds the solution and fails if there are any compiler warnings.
    This script is designed to be called from a git pre-commit hook.
    
.PARAMETER TreatWarningsAsErrors
    Exit with error code if warnings are found (default: true)
    
.EXAMPLE
    .\scripts\check-compile-warnings.ps1
#>

param(
    [switch]$TreatWarningsAsErrors = $true
)

$ErrorActionPreference = "Stop"

# Get list of staged C# files
function Get-StagedCSharpFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -match '\.cs$' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        return @()
    }
}

# Build solution and check for warnings
function Test-BuildWarnings {
    try {
        # Build with detailed output to capture warnings
        $buildOutput = dotnet build IcmMcpServer.sln --no-incremental --verbosity quiet 2>&1 | Out-String
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "❌ Build failed" -ForegroundColor Red
            Write-Host $buildOutput
            return $false
        }
        
        # Check for warnings in output
        $warningPattern = '(?m)^\s*.*?warning\s+CS\d+:'
        $warnings = [regex]::Matches($buildOutput, $warningPattern)
        
        if ($warnings.Count -gt 0) {
            Write-Host "❌ $($warnings.Count) compiler warning(s):" -ForegroundColor Red
            foreach ($warning in $warnings) {
                Write-Host "  $($warning.Value.Trim())" -ForegroundColor Yellow
            }
            return $false
        }
        
        Write-Host "PASS: Build warnings = 0" -ForegroundColor Green
        return $true
    }
    catch {
        Write-Host "❌ Build failed: $_" -ForegroundColor Red
        return $false
    }
}

# Main execution
$stagedFiles = Get-StagedCSharpFiles

if ($stagedFiles.Count -eq 0) {
    exit 0
}

# Check for compile warnings
if (-not (Test-BuildWarnings)) {
    if ($TreatWarningsAsErrors) {
        exit 1
    }
}

exit 0
