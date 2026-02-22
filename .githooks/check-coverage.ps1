#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Pre-commit coverage checker for Python projects
    
.DESCRIPTION
    Wrapper that calls the Python coverage checker script.
    This script is designed to be called from a git pre-commit hook.
    
.EXAMPLE
    .\.githooks\check-coverage.ps1
#>

$ErrorActionPreference = "Stop"

# Call the Python coverage checker
& python "$PSScriptRoot\check-coverage.py"
exit $LASTEXITCODE
