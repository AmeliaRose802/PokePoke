#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Pre-commit file length checker for Python and desktop JS/TS projects
    
.DESCRIPTION
    Verifies that source files don't exceed the maximum line limit.
    Python files: 400 lines (configurable via MAX_LINES env var)
    Desktop JS/TS files: 500 lines (configurable via MAX_LINES_JS env var)
    This script is designed to be called from a git pre-commit hook.
    
.PARAMETER MaxLines
    Maximum lines allowed per Python file (default: 400)

.PARAMETER MaxLinesJs
    Maximum lines allowed per desktop JS/TS file (default: 500)
    
.EXAMPLE
    .\scripts\check-file-length.ps1
#>

param(
    [int]$MaxLines = $(if ($env:MAX_LINES) { [int]$env:MAX_LINES } else { 400 }),
    [int]$MaxLinesJs = $(if ($env:MAX_LINES_JS) { [int]$env:MAX_LINES_JS } else { 500 })
)

$ErrorActionPreference = "Stop"

# Load shared staged-file utilities
$stagedUtils = Join-Path $PSScriptRoot "staged-files-utils.ps1"
if (-not (Test-Path $stagedUtils)) {
    throw "staged-files-utils.ps1 not found at $stagedUtils"
}
. $stagedUtils

# Count non-empty lines in a file
function Get-FileLineCount {
    param([string]$FilePath)
    
    if (-not (Test-Path $FilePath)) {
        return 0
    }
    
    try {
        $lines = Get-Content $FilePath -ErrorAction Stop
        if ($null -eq $lines) {
            return 0
        }
        
        # Count only non-empty lines (lines that are not null/empty/whitespace-only)
        $nonEmptyLines = $lines | Where-Object { $_ -and $_.Trim() -ne "" }
        return $nonEmptyLines.Count
    }
    catch {
        Write-Warning "Could not read file: $FilePath"
        return 0
    }
}

# Get list of staged desktop JS/TS files (source only, no tests)
function Get-StagedDesktopFilesForLength {
    return Get-StagedFiles -Pattern '^desktop/src/.*\.(ts|tsx|js|jsx)$' `
        -DenyPatterns @('node_modules/', 'dist/') `
        -ExcludeTests
}

# Check file lengths
function Test-FileLengths {
    param(
        [string[]]$Files,
        [int]$Limit
    )
    
    if ($Files.Count -eq 0) {
        return $true
    }
    
    $violations = @()
    $passedCount = 0
    
    foreach ($file in $Files) {
        $lineCount = Get-FileLineCount -FilePath $file
        
        if ($lineCount -gt $Limit) {
            $violations += [PSCustomObject]@{
                File = $file
                Lines = $lineCount
                Excess = $lineCount - $Limit
            }
        }
        else {
            $passedCount++
        }
    }
    
    if ($violations.Count -gt 0) {
        Write-Host "❌ $($violations.Count) file(s) exceed $Limit non-blank lines:" -ForegroundColor Red
        $violations | ForEach-Object {
            Write-Host "  $($_.File): $($_.Lines) non-blank lines (+$($_.Excess))" -ForegroundColor Red
        }
        Write-Host "  NOTE: Blank lines are NOT counted. Do NOT delete blank lines to reduce length." -ForegroundColor Yellow
        Write-Host "  Instead, extract functions/classes into separate modules." -ForegroundColor Yellow
        return $false
    }
    
    Write-Host "PASS: File length <$Limit non-blank lines ($passedCount files)" -ForegroundColor Green
    return $true
}

# Main execution
$stagedPythonFiles = Get-StagedFiles -Pattern '\.py$' `
    -DenyPatterns @('node_modules/', '__pycache__/') `
    -ExcludeTests
$stagedDesktopFiles = Get-StagedDesktopFilesForLength

if ($stagedPythonFiles.Count -eq 0 -and $stagedDesktopFiles.Count -eq 0) {
    exit 0
}

$allPassed = $true

# Check Python file lengths
if ($stagedPythonFiles.Count -gt 0) {
    if (-not (Test-FileLengths -Files $stagedPythonFiles -Limit $MaxLines)) {
        $allPassed = $false
    }
}

# Check desktop JS/TS file lengths
if ($stagedDesktopFiles.Count -gt 0) {
    if (-not (Test-FileLengths -Files $stagedDesktopFiles -Limit $MaxLinesJs)) {
        $allPassed = $false
    }
}

if (-not $allPassed) {
    exit 1
}

exit 0
