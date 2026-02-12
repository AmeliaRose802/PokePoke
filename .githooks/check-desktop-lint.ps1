#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Desktop ESLint check for pre-commit hook

.DESCRIPTION
    Detects staged desktop React files and, when found, runs `npm run lint`
    inside the desktop/ workspace to enforce the ESLint ruleset (including
    the inline style ban).

.EXAMPLE
    .\.githooks\check-desktop-lint.ps1
#>

param()

$ErrorActionPreference = "Stop"

# Resolve repo root (supports worktrees)
$repoRoot = git rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRoot)) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}

Set-Location $repoRoot

function Get-StagedDesktopLintFiles {
    try {
        $output = git diff --cached --name-only --diff-filter=ACM 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) {
            return @()
        }

        return $output -split "`n" |
            Where-Object { $_ -match '^desktop/.*\.(ts|tsx|js|jsx|css)$' } |
            Where-Object { $_ -notmatch '(node_modules|dist|build)' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -ne '' }
    }
    catch {
        Write-Host "Failed to inspect staged files for desktop lint: $_" -ForegroundColor Red
        return @()
    }
}

$stagedFiles = Get-StagedDesktopLintFiles

if ($stagedFiles.Count -eq 0) {
    Write-Host "No staged desktop files require ESLint" -ForegroundColor Gray
    exit 0
}

$desktopDir = Join-Path $repoRoot "desktop"
if (-not (Test-Path $desktopDir)) {
    Write-Host "Desktop directory not found at $desktopDir" -ForegroundColor Red
    exit 1
}

Write-Host "🧼 Running ESLint for $($stagedFiles.Count) staged desktop file(s)..." -ForegroundColor Cyan
Write-Host "      (Invoking 'npm run lint -- --max-warnings=0')" -ForegroundColor DarkGray

Push-Location $desktopDir
try {
    npm run lint -- --max-warnings=0
    $lintExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($lintExitCode -ne 0) {
    Write-Host ""
    Write-Host "❌ Desktop ESLint failures detected" -ForegroundColor Red
    Write-Host "Fix lint issues reported above (inline styles are prohibited) before committing." -ForegroundColor Yellow
    exit 1
}

Write-Host "✅ Desktop ESLint passed" -ForegroundColor Green
exit 0
