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

# Get list of staged Python files
function Get-StagedPythonFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to get staged files"
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -ne '' } |
            Where-Object { $_ -match '\.py$' } |
            Where-Object { $_ -notmatch 'node_modules/' } |
            Where-Object { $_ -notmatch '^tests/' } |
            Where-Object { $_ -notmatch 'test_.*\.py$' } |
            Where-Object { $_ -notmatch '/[Tt]ests?/' } |
            Where-Object { $_ -notmatch '__pycache__/' } |
            ForEach-Object { $_.Trim() }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}

# Count lines in a file
function Get-FileLineCount {
    param([string]$FilePath)
    
    if (-not (Test-Path $FilePath)) {
        return 0
    }
    
    try {
        $lines = Get-Content $FilePath -ErrorAction Stop
        return $lines.Count
    }
    catch {
        Write-Warning "Could not read file: $FilePath"
        return 0
    }
}

# Get list of staged desktop JS/TS files
function Get-StagedDesktopFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to get staged files"
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -ne '' } |
            Where-Object { $_ -match '^desktop/src/.*\.(ts|tsx|js|jsx)$' } |
            Where-Object { $_ -notmatch 'node_modules/' } |
            Where-Object { $_ -notmatch 'dist/' } |
            Where-Object { $_ -notmatch '\.test\.(ts|tsx|js|jsx)$' } |
            Where-Object { $_ -notmatch '\.spec\.(ts|tsx|js|jsx)$' } |
            Where-Object { $_ -notmatch '/__tests__/' } |
            Where-Object { $_ -notmatch '/[Tt]ests?/' } |
            ForEach-Object { $_.Trim() }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
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
            Write-Host "  ❌ $file - $lineCount lines (exceeds limit by $($lineCount - $Limit))" -ForegroundColor Red
        }
        else {
            $passedCount++
        }
    }
    
    if ($violations.Count -gt 0) {
        Write-Host "❌ $($violations.Count) file(s) exceed $Limit lines:" -ForegroundColor Red
        $violations | ForEach-Object {
            Write-Host "  $($_.File): $($_.Lines) lines (+$($_.Excess))" -ForegroundColor Red
        }
        return $false
    }
    
    Write-Host "PASS: File length <$Limit lines ($passedCount files)" -ForegroundColor Green
    return $true
}

# Main execution
$stagedPythonFiles = Get-StagedPythonFiles
$stagedDesktopFiles = Get-StagedDesktopFiles

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
