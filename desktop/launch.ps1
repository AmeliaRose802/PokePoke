<#
.SYNOPSIS
    Launch PokePoke Desktop - a native desktop app via pywebview.

.DESCRIPTION
    Single command to start the PokePoke desktop application.
    One Python process. No server. No browser. No ports.

    If the React frontend hasn't been built yet, this script will build it first.

.EXAMPLE
    .\desktop\launch.ps1
#>

$ErrorActionPreference = 'Stop'

$desktopDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $desktopDir

Write-Host "⚡ PokePoke Desktop" -ForegroundColor Cyan
Write-Host "===================" -ForegroundColor DarkCyan
Write-Host ""

# Check if frontend is built
$distDir = Join-Path $desktopDir "dist"
if (-not (Test-Path (Join-Path $distDir "index.html"))) {
    Write-Host "📦 Building frontend (first time only)..." -ForegroundColor Yellow

    if (-not (Test-Path (Join-Path $desktopDir "node_modules"))) {
        Push-Location $desktopDir
        npm install
        Pop-Location
    }

    Push-Location $desktopDir
    npm run build
    Pop-Location

    Write-Host "✅ Frontend built" -ForegroundColor Green
    Write-Host ""
}

Write-Host "🚀 Starting PokePoke Desktop..." -ForegroundColor Yellow
Write-Host "   Single process. No server. No browser." -ForegroundColor DarkGray
Write-Host ""

# Activate venv if present
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    & $venvPython -m pokepoke.orchestrator --autonomous --continuous
} else {
    python -m pokepoke.orchestrator --autonomous --continuous
}

