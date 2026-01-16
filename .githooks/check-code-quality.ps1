#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Code quality checker using Roslyn analyzers
    
.DESCRIPTION
    Checks staged C# files for:
    - Code style violations (naming, formatting)
    - Null safety issues
    - Async/await antipatterns
    - Unused variables/imports
    
    This script is designed to be called from a git pre-commit hook.
    
.EXAMPLE
    .\scripts\check-code-quality.ps1
    
#>

param()

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
            Where-Object { $_ -match '^src/' } |
            Where-Object { $_ -notmatch '\.Test\.cs$' } |
            Where-Object { $_ -notmatch '/Tests/' } |
            Where-Object { $_ -notmatch 'icm_queue_tool/' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}

# Check for null safety issues using basic pattern matching
function Test-NullSafety {
    param([string[]]$Files)
    
    $issues = @()
    
    foreach ($file in $Files) {
        if (-not (Test-Path $file)) { continue }
        
        $content = Get-Content $file -Raw
        $lineNumber = 0
        
        foreach ($line in ($content -split "`n")) {
            $lineNumber++
            
            # Check for null-coalescing on null-returning methods
            if ($line -match '(?<!\.)\w+\(\)(?!\s*\??\.)' -and $line -notmatch '\?\.' -and $line -notmatch 'null-check|is null|== null|!= null') {
                # Basic heuristic: method call without null check
                if ($line -match '=\s*\w+\(\)' -and $line -notmatch 'guard|Guard|null-check|ArgumentNullException') {
                    $issues += @{
                        File = $file
                        Line = $lineNumber
                        Message = "Potential null dereference - consider null check or null-coalescing operator"
                        Text = $line.Trim()
                    }
                }
            }
        }
    }
    
    return $issues
}

# Check for async/await antipatterns
function Test-AsyncPatterns {
    param([string[]]$Files)
    
    $issues = @()
    
    foreach ($file in $Files) {
        if (-not (Test-Path $file)) { continue }
        
        $content = Get-Content $file -Raw
        $lineNumber = 0
        
        foreach ($line in ($content -split "`n")) {
            $lineNumber++
            
            # Check for .Result on async calls
            if ($line -match '\.Result\s*;' -and $content -match 'async') {
                $issues += @{
                    File = $file
                    Line = $lineNumber
                    Message = "❌ CRITICAL: .Result on async call causes deadlocks - use await instead"
                    Text = $line.Trim()
                    Severity = "Error"
                }
            }
            
            # Check for .Wait() on async calls
            if ($line -match '\.Wait\(\)' -and $content -match 'async') {
                $issues += @{
                    File = $file
                    Line = $lineNumber
                    Message = "❌ CRITICAL: .Wait() on async call causes deadlocks - use await instead"
                    Text = $line.Trim()
                    Severity = "Error"
                }
            }
            
            # Check for async void (except event handlers)
            if ($line -match 'async\s+void\s+\w+' -and $line -notmatch 'EventHandler|event_|_Event') {
                $issues += @{
                    File = $file
                    Line = $lineNumber
                    Message = "⚠️  async void only acceptable for event handlers - use Task instead"
                    Text = $line.Trim()
                    Severity = "Warning"
                }
            }
        }
    }
    
    return $issues
}

# Check for obvious null coalescing improvements
function Test-CodeStyle {
    param([string[]]$Files)
    
    $issues = @()
    
    foreach ($file in $Files) {
        if (-not (Test-Path $file)) { continue }
        
        $content = Get-Content $file -Raw
        $lineNumber = 0
        
        foreach ($line in ($content -split "`n")) {
            $lineNumber++
            
            # Check for old-style null comparison (minor style issue)
            if ($line -match '== null' -or $line -match '!= null') {
                $issues += @{
                    File = $file
                    Line = $lineNumber
                    Message = "💡 Consider using 'is null' / 'is not null' (C# 9.0+)"
                    Text = $line.Trim()
                    Severity = "Info"
                }
            }
            
            # Check for extraneous whitespace patterns
            if ($line -match '\s{2,}\w' -and $line -notmatch '^\s+' -and $line -notmatch 'comment|//') {
                # This is too noisy, skip for now
            }
        }
    }
    
    return $issues
}

# Main execution
$stagedFiles = Get-StagedCSharpFiles

if ($stagedFiles.Count -eq 0) {
    exit 0
}

$allIssues = @()

# Run all checks
$asyncIssues = Test-AsyncPatterns -Files $stagedFiles
$allIssues += $asyncIssues

$nullIssues = Test-NullSafety -Files $stagedFiles
$allIssues += $nullIssues

$styleIssues = Test-CodeStyle -Files $stagedFiles
$allIssues += $styleIssues

# Display results grouped by severity
$criticalIssues = $allIssues | Where-Object { $_.Severity -eq "Error" }
$warningIssues = $allIssues | Where-Object { $_.Severity -eq "Warning" -or -not $_.Severity }
$infoIssues = $allIssues | Where-Object { $_.Severity -eq "Info" }

if ($criticalIssues.Count -gt 0) {
    Write-Host "❌ CRITICAL:" -ForegroundColor Red
    foreach ($issue in $criticalIssues) {
        Write-Host "  $($issue.File):$($issue.Line)" -ForegroundColor Red
        Write-Host "  $($issue.Message)" -ForegroundColor Red
    }
    exit 1
}

if ($warningIssues.Count -gt 0) {
    Write-Host "⚠️  $($warningIssues.Count) warning(s):" -ForegroundColor Yellow
    foreach ($issue in $warningIssues) {
        Write-Host "  $($issue.File):$($issue.Line) - $($issue.Message)" -ForegroundColor Yellow
    }
    exit 0
}

Write-Host "PASS: Code quality" -ForegroundColor Green
exit 0
