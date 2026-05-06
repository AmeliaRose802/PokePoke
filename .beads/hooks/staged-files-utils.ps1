#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Shared staged-file utilities for pre-commit hooks

.DESCRIPTION
    Provides a single Get-StagedFiles function with configurable parameters
    to replace duplicated staged-file logic across .githooks scripts.

    Supports:
    - Pattern-based file matching (regex)
    - Configurable deny patterns for filtering
    - Test file exclusion (Python and desktop conventions)
    - Source-only filtering (restrict to src/pokepoke/)
    - Full path resolution with existence checking

.NOTES
    ⚠️  CRITICAL: This file is protected by CODEOWNERS
    Any modifications require @ameliapayne approval

.EXAMPLE
    . "$PSScriptRoot\staged-files-utils.ps1"
    $pyFiles = Get-StagedFiles -Pattern '\.py$' -DenyPatterns @('venv','__pycache__')
#>

function Get-StagedFiles {
    <#
    .SYNOPSIS
        Returns staged files matching the given criteria.

    .PARAMETER Pattern
        Regex pattern that file paths must match (e.g. '\.py$').

    .PARAMETER DenyPatterns
        Array of regex patterns to reject matching files.

    .PARAMETER ExcludeTests
        Exclude common test files and directories (Python and desktop conventions).

    .PARAMETER SourceOnly
        Restrict results to files under src/pokepoke/.

    .PARAMETER ResolveFullPath
        Resolve relative paths to absolute paths using RepoRoot, filtering out
        files that do not exist on disk.

    .PARAMETER RepoRoot
        Repository root for full-path resolution. Required when -ResolveFullPath
        is specified.
    #>
    param(
        [Parameter(Mandatory)]
        [string]$Pattern,

        [string[]]$DenyPatterns = @(),

        [switch]$ExcludeTests,

        [switch]$SourceOnly,

        [switch]$ResolveFullPath,

        [string]$RepoRoot
    )

    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) {
            return @()
        }

        $files = $output -split "`n" |
            Where-Object { $_ -ne '' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' } |
            Where-Object { $_ -match $Pattern }

        # Apply SourceOnly filter (restrict to src/pokepoke/)
        if ($SourceOnly) {
            $files = $files | Where-Object { $_ -match '^src/pokepoke/' }
        }

        # Apply user-supplied deny patterns
        foreach ($deny in $DenyPatterns) {
            $files = $files | Where-Object { $_ -notmatch $deny }
        }

        # Apply test-file exclusion patterns (covers Python and desktop)
        if ($ExcludeTests) {
            $files = $files |
                Where-Object { $_ -notmatch 'test_.*\.py$' } |
                Where-Object { $_ -notmatch '_test\.py$' } |
                Where-Object { $_ -notmatch '^tests/' } |
                Where-Object { $_ -notmatch '/[Tt]ests?/' } |
                Where-Object { $_ -notmatch '\.test\.(ts|tsx|js|jsx)$' } |
                Where-Object { $_ -notmatch '\.spec\.(ts|tsx|js|jsx)$' } |
                Where-Object { $_ -notmatch '/__tests__/' }
        }

        # Resolve to absolute paths and check existence
        if ($ResolveFullPath) {
            if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
                Write-Error "-RepoRoot is required when -ResolveFullPath is specified"
                return @()
            }
            $files = $files |
                ForEach-Object { Join-Path $RepoRoot $_ } |
                Where-Object { Test-Path $_ }
        }

        # Force array output (avoid scalar unwrapping)
        return @($files)
    }
    catch {
        Write-Error "Failed to get staged files: $_"
        return @()
    }
}
