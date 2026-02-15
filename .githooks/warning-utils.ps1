#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Shared helper functions for warning enforcement in quality gates.

.DESCRIPTION
    Provides lightweight pattern matching utilities to detect compiler or
    linter warnings that should block commits even when exit codes are zero.
#>

function Get-WarningMatches {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Lines
    )

    $warningPatterns = @(
        '(?i)^\s*(?:warn(?:ing)?|npm\s+warn|\(!\))\b',
        '(?i)\b\w*warning(?!s):'
    )

    $matches = @()

    foreach ($line in $Lines) {
        if ($null -eq $line) {
            continue
        }

        $text = [string]$line
        foreach ($pattern in $warningPatterns) {
            if ($text -match $pattern) {
                $matches += $text.TrimEnd()
                break
            }
        }
    }

    return $matches
}
