<#
.SYNOPSIS
    Launch PokePoke Desktop in development mode with hot reload.

.DESCRIPTION
    Starts the Vite dev server for the React frontend, then launches the
    Python desktop app pointing at the dev server.  Frontend changes are
    reflected instantly via Vite HMR — no manual rebuild needed.

.EXAMPLE
    .\desktop\dev.ps1
#>

$ErrorActionPreference = 'Stop'

$desktopDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $desktopDir

Write-Host "🔥 PokePoke Desktop - Dev Mode (Hot Reload)" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor DarkCyan
Write-Host ""

# Install dependencies if needed
if (-not (Test-Path (Join-Path $desktopDir "node_modules"))) {
    Write-Host "📦 Installing npm dependencies..." -ForegroundColor Yellow
    Push-Location $desktopDir
    npm install
    Pop-Location
}

# Start Vite dev server in the background
Write-Host "🚀 Starting Vite dev server..." -ForegroundColor Yellow
$viteJob = Start-Process -FilePath "npm" `
    -ArgumentList "run", "dev" `
    -WorkingDirectory $desktopDir `
    -PassThru -NoNewWindow

# Wait for Vite to be ready
Write-Host "   Waiting for Vite at http://localhost:5173..." -ForegroundColor DarkGray
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
        $ready = $true
        break
    } catch {
        # Not ready yet
    }
}

if (-not $ready) {
    Write-Host "❌ Vite dev server did not start in time." -ForegroundColor Red
    Stop-Process -Id $viteJob.Id -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "✅ Vite dev server ready" -ForegroundColor Green
Write-Host "   Frontend changes will hot-reload automatically." -ForegroundColor DarkGray
Write-Host ""

# Set env var so Python knows to use the dev server
$env:POKEPOKE_DEV = "1"

# Launch the desktop app
Write-Host "🖥️  Starting PokePoke Desktop..." -ForegroundColor Yellow
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
try {
    if (Test-Path $venvPython) {
        & $venvPython -m pokepoke --autonomous --continuous @args
    } else {
        python -m pokepoke --autonomous --continuous @args
    }
} finally {
    # Clean up Vite dev server when the app exits
    Write-Host ""
    Write-Host "🧹 Stopping Vite dev server..." -ForegroundColor DarkGray
    if (-not $viteJob.HasExited) {
        Stop-Process -Id $viteJob.Id -ErrorAction SilentlyContinue
    }
    Write-Host "👋 Done." -ForegroundColor DarkGray
}
