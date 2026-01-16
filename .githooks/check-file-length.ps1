#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Pre-commit file length checker for C# projects
    
.DESCRIPTION
    Verifies that C# files don't exceed the maximum line limit.
    This script is designed to be called from a git pre-commit hook.
    
.PARAMETER MaxLines
    Maximum lines allowed per file (default: 500)
    
.EXAMPLE
    .\scripts\check-file-length.ps1
#>

param(
    [int]$MaxLines = [int]($env:MAX_LINES ?? 500)
)

$ErrorActionPreference = "Stop"

# Get list of staged C# files
function Get-StagedCSharpFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Failed to get staged files"
            return @()
        }
        
        return $output -split "`n" |
            Where-Object { $_ -ne '' } |
            Where-Object { $_ -match '\.cs$' } |
            Where-Object { $_ -notmatch 'node_modules/' } |
            Where-Object { $_ -notmatch '^tests/' } |
            Where-Object { $_ -notmatch '\.Test\.cs$' } |
            Where-Object { $_ -notmatch '/[Tt]ests?/' } |
            Where-Object { $_ -notmatch 'icm_queue_tool/' } |
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

# Check file lengths
function Test-FileLengths {
    param([string[]]$Files)
    
    if ($Files.Count -eq 0) {
        return $true
    }
    
    $violations = @()
    $passedCount = 0
    
    foreach ($file in $Files) {
        $lineCount = Get-FileLineCount -FilePath $file
        
        if ($lineCount -gt $MaxLines) {
            $violations += [PSCustomObject]@{
                File = $file
                Lines = $lineCount
                Excess = $lineCount - $MaxLines
            }
            Write-Host "  ❌ $file - $lineCount lines (exceeds limit by $($lineCount - $MaxLines))" -ForegroundColor Red
        }
        else {
            $passedCount++
        }
    }
    
    if ($violations.Count -gt 0) {
        Write-Host "❌ $($violations.Count) file(s) exceed $MaxLines lines:" -ForegroundColor Red
        $violations | ForEach-Object {
            Write-Host "  $($_.File): $($_.Lines) lines (+$($_.Excess))" -ForegroundColor Red
        }
        return $false
    }
    
    Write-Host "PASS: File length <$MaxLines lines ($passedCount files)" -ForegroundColor Green
    return $true
}

# Main execution
$stagedFiles = Get-StagedCSharpFiles

if ($stagedFiles.Count -eq 0) {
    exit 0
}

# Check lengths
if (-not (Test-FileLengths -Files $stagedFiles)) {
    exit 1
}

exit 0
